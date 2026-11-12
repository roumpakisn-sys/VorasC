"""Real rollback/concurrency tests against an isolated PostgreSQL service in CI."""
import json
import os
from pathlib import Path
import threading
import unittest
import uuid

DSN = os.environ.get('TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'Set TEST_DATABASE_URL to an isolated PostgreSQL test database')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.pg = psycopg
        cls.db = psycopg.connect(DSN, autocommit=True)
        cls.db.execute('''
            do $$ begin
                if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if;
                if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if;
                if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role; end if;
            end $$;
            create table projects(id text primary key, name text, color text);
            create table employees(id text primary key, name text, status text default 'Ενεργός');
            create table leaves(id text primary key, "employeeId" text, "startDate" date, "endDate" date);
            create table assignments(
                id text primary key, "employeeId" text, "projectId" text references projects(id), date date,
                "startTime" text, "endTime" text, "arrivalTime" text,
                "colorName" text, "colorHex" text, notes text,
                is_cancelled boolean default false, cancel_reason text,
                recurring_id text, is_general boolean default false,
                updated_at timestamptz default now(), created_at timestamptz default now(),
                preserved_column text default 'keep me'
            );
            create table deleted_records(id bigserial primary key, table_name text, record_id text, created_at timestamptz default now());
        ''')
        root = Path(__file__).resolve().parents[1]
        cls.db.execute((root / 'sql/employee_availability_rules.sql').read_text())
        cls.db.execute((root / 'sql/atomic_assignment_changes.sql').read_text())
        # Migration must be safe to apply again.
        cls.db.execute((root / 'sql/atomic_assignment_changes.sql').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.execute('drop trigger if exists injected_failure on assignments')
        self.db.execute('truncate assignments, projects, employees, leaves, employee_availability_rules, deleted_records, assignment_write_receipts cascade')
        self.db.execute("insert into projects values ('p', 'Project', '#aaa')")
        self.db.execute("insert into employees(id, name) values ('e', 'Employee'), ('e2', 'Second')")
        self.db.execute('''insert into assignments(id,"employeeId","projectId",date,"startTime","endTime",notes)
                           values ('a','e','p','2026-11-12','09:00','12:00','old'),
                                  ('b','e2','p','2026-11-12','09:00','12:00','old')''')

    def rows(self):
        return self.db.execute('select to_jsonb(a) from assignments a order by id').fetchall()

    def expected(self):
        return [r[0] for r in self.rows()]

    def proposed(self):
        from assignment_policy import EDIT_FIELDS
        return [{k: v for k, v in r.items() if k in (*EDIT_FIELDS, 'id')} for r in self.expected()]

    def context(self, ids=('e', 'e2')):
        return self.db.execute('select assignment_validation_context(%s::jsonb,%s::date,%s::date)',
                               (json.dumps(ids), '2026-11-11', '2026-11-13')).fetchone()[0]

    def save(self, before, after, project=None, context=None, request=None, db=None):
        conn = db or self.db
        return conn.execute('select save_assignment_changes(%s::uuid,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)',
                            (request or str(uuid.uuid4()), json.dumps(before), json.dumps(after),
                             json.dumps(project) if project else None, json.dumps(context) if context else None)).fetchone()[0]

    def test_group_update_preserves_ids_and_unedited_columns(self):
        before, after = self.expected(), self.proposed()
        for r in after: r['notes'] = 'changed'
        result = self.save(before, after)
        self.assertEqual([r['id'] for r in result['rows']], ['a', 'b'])
        self.assertTrue(all(r['notes'] == 'changed' and r['preserved_column'] == 'keep me' for r in result['rows']))
        self.assertEqual(result['rows'][0]['created_at'], before[0]['created_at'])
        self.assertNotEqual(result['rows'][0]['updated_at'], before[0]['updated_at'])

    def test_second_row_failure_rolls_back_first_and_project(self):
        before, after = self.expected(), self.proposed()
        self.db.execute('''create or replace function inject_failure() returns trigger language plpgsql as $$
            begin if new.id='b' then raise exception 'injected failure'; end if; return new; end $$;
            create trigger injected_failure before update on assignments for each row execute function inject_failure();''')
        for r in after: r.update(notes='changed', projectId='newp')
        with self.assertRaises(self.pg.Error):
            self.save(before, after, project={'id': 'newp', 'name': 'New', 'color': '#fff'})
        self.assertEqual(self.expected(), before)
        self.assertEqual(self.db.execute("select count(*) from projects where id='newp'").fetchone()[0], 0)
        self.assertEqual(self.db.execute('select count(*) from assignment_write_receipts').fetchone()[0], 0)

    def test_changed_original_rejects_entire_group(self):
        before, after = self.expected(), self.proposed()
        self.db.execute("update assignments set notes='other user' where id='b'")
        after[0]['notes'] = 'changed'
        with self.assertRaisesRegex(self.pg.Error, 'Stale assignment'): self.save(before, after)
        self.assertEqual(self.expected()[0]['notes'], 'old')

    def test_missing_original_rejects(self):
        before, after = self.expected(), self.proposed()
        self.db.execute("delete from assignments where id='b'")
        with self.assertRaisesRegex(self.pg.Error, 'removed'): self.save(before, after)

    def test_remove_and_add_worker_logs_deletion_atomically(self):
        before, after, ctx = self.expected(), self.proposed(), self.context()
        after[1]['id'] = 'new'
        result = self.save(before, after, context=ctx)
        self.assertEqual(result['deleted_ids'], ['b'])
        self.assertEqual(self.db.execute('select record_id from deleted_records').fetchall(), [('b',)])
        self.assertEqual([r['id'] for r in result['rows']], ['a', 'new'])

    def test_insert_failure_retains_original_workers(self):
        before, after, ctx = self.expected(), self.proposed(), self.context()
        after[1].update(id='new', projectId='missing')
        with self.assertRaises(self.pg.Error): self.save(before, after, context=ctx)
        self.assertEqual(self.expected(), before)
        self.assertEqual(self.db.execute('select count(*) from deleted_records').fetchone()[0], 0)

    def test_receipt_replay_is_idempotent_and_readable(self):
        before, after, request = self.expected(), self.proposed(), str(uuid.uuid4())
        after[0]['notes'] = 'new'
        result = self.save(before, after, request=request)
        self.assertEqual(self.save(before, after, request=request), result)
        self.assertEqual(self.db.execute('select assignment_write_result(%s::uuid)', (request,)).fetchone()[0], result)
        self.assertEqual(self.db.execute('select count(*) from assignment_write_receipts').fetchone()[0], 1)
        after[0]['notes'] = 'different'
        with self.assertRaisesRegex(self.pg.Error, 'reused'): self.save(before, after, request=request)

    def test_reactivation_requires_context(self):
        self.db.execute('update assignments set is_cancelled=true')
        before, after = self.expected(), self.proposed()
        after[0]['is_cancelled'] = False
        with self.assertRaisesRegex(self.pg.Error, 'validation scope'): self.save(before, after)

    def test_new_leave_rule_employee_or_assignment_invalidates_snapshot(self):
        mutations = [
            "insert into leaves values ('l', 'e', '2026-11-12', '2026-11-12')",
            "insert into employee_availability_rules(employee_id, scope, rule_date, kind) values ('e','date','2026-11-12','unavailable')",
            "update employees set status='Ανενεργός' where id='e'",
            '''insert into assignments(id,"employeeId","projectId",date,"startTime","endTime") values ('c','e','p','2026-11-12','11:00','13:00')''',
        ]
        for sql in mutations:
            with self.subTest(sql=sql):
                before, after, ctx = self.expected(), self.proposed(), self.context()
                after[0]['endTime'] = '14:00'
                self.db.execute(sql)
                with self.assertRaisesRegex(self.pg.Error, 'Availability changed'): self.save(before, after, context=ctx)
                self.assertEqual(self.expected()[0]['endTime'], '12:00')

    def test_two_concurrent_edits_only_one_commits(self):
        before, proposed = self.expected(), self.proposed()
        barrier = threading.Barrier(2)
        results = []
        def worker(note):
            with self.pg.connect(DSN, autocommit=True) as db:
                after = [{**r, 'notes': note} for r in proposed]
                barrier.wait(timeout=5)
                try:
                    self.save(before, after, db=db)
                    results.append('saved')
                except self.pg.Error:
                    results.append('rejected')
        threads = [threading.Thread(target=worker, args=(note,)) for note in ('first', 'second')]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)
        self.assertEqual(sorted(results), ['rejected', 'saved'])
        self.assertEqual(len({r['notes'] for r in self.expected()}), 1)

    def test_context_not_truncated_at_rest_page_size(self):
        self.db.execute('''insert into assignments(id,"employeeId","projectId",date,"startTime","endTime")
                           select 'x'||n,'e','p','2026-11-12','13:00','15:00' from generate_series(1,1200) n''')
        self.assertEqual(len(self.context()['assignments']), 1202)

    def test_untrusted_roles_cannot_execute(self):
        for role in ('anon', 'authenticated'):
            self.assertFalse(self.db.execute("select has_function_privilege(%s, 'public.save_assignment_changes(uuid,jsonb,jsonb,jsonb,jsonb)', 'execute')", (role,)).fetchone()[0])
            self.assertFalse(self.db.execute("select has_table_privilege(%s, 'public.assignment_write_receipts', 'select')", (role,)).fetchone()[0])
