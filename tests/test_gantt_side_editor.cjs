const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const {install} = require('../gantt_side_editor.js');

function fixture() {
  const dom = new JSDOM(`<!doctype html><html><head></head><body>
    <button id="other">Other bar</button><label><input id="toggle" type="checkbox"></label>
    <div class="st-key-test"><button id="close">Close</button>
    <div data-testid="stForm"><input id="notes" value="original">
    <div data-baseweb="select"><span id="workers">Α, Β</span></div>
    <span data-staffpro-form="bar-a"></span>
    <button id="save">Αποθήκευση</button><button id="preview">Προεπισκόπηση</button></div></div>
    </body></html>`, {url: 'https://example.test'});
  const win = dom.window;
  let prompts = 0, accept = false;
  win.confirm = () => {prompts++; return accept;};
  const state = install(win, {selector: '.st-key-test', identity: 'bar-a', barId: 'a'});
  return {win, state, get: id => win.document.getElementById(id),
    prompts: () => prompts, accept: () => {accept = true;},
    cleanup: () => {win.staffProSideEditor?.cleanup(); win.close();}};
}

test('clean close works, dirty cancellation blocks before application handlers', () => {
  const f = fixture(); let clicks = 0;
  f.get('close').addEventListener('click', () => clicks++);
  f.get('close').click(); assert.equal(clicks, 1); assert.equal(f.prompts(), 0);
  f.get('notes').value = 'draft'; f.get('close').click();
  assert.equal(clicks, 1); assert.equal(f.prompts(), 1); assert.equal(f.get('notes').value, 'draft');
  f.accept(); f.get('close').click(); assert.equal(clicks, 2); f.cleanup();
});

test('multiworker changes and cross-frame bar selection are protected', () => {
  const f = fixture(); f.get('workers').textContent = 'Α, Γ';
  assert.equal(f.state.allowLeave('a'), true); assert.equal(f.prompts(), 0);
  assert.equal(f.state.allowLeave('b'), false); assert.equal(f.prompts(), 1);
  f.cleanup();
});

test('preview and save do not discard draft, failed-save rerun retains protection', () => {
  const f = fixture(); f.get('notes').value = 'draft';
  f.get('preview').click(); f.get('save').click(); assert.equal(f.prompts(), 0);
  f.state.allowLeave('b');
  const next = install(f.win, {selector: '.st-key-test', identity: 'bar-a', barId: 'a'});
  assert.equal(next.allowLeave('b'), false); assert.equal(f.prompts(), 2);
  f.cleanup();
});

test('next bar gets clean baseline and old listeners are removed', () => {
  const f = fixture(); f.get('notes').value = 'draft'; f.state.allowLeave('b');
  f.get('notes').value = 'second bar';
  f.win.document.querySelector('[data-staffpro-form]').setAttribute('data-staffpro-form', 'bar-b');
  const next = install(f.win, {selector: '.st-key-test', identity: 'bar-b', barId: 'b'});
  assert.equal(next.allowLeave('a'), true); assert.equal(f.prompts(), 1);
  f.get('notes').value = 'second draft'; f.get('close').click();
  assert.equal(f.prompts(), 2); f.cleanup();
});

test('cleanup restores inline presentation and removes interception', () => {
  const f = fixture(); f.get('notes').value = 'draft'; f.state.cleanup();
  assert.equal(f.win.document.querySelector('.staffpro-drawer-active'), null);
  assert.equal(f.win.document.querySelector('style'), null);
  assert.equal(f.win.staffProSideEditor, undefined);
  f.get('close').click(); assert.equal(f.prompts(), 0); f.cleanup();
});

test('navigation away cleans up, reverting a field is clean', async () => {
  const f = fixture(); f.get('notes').value = 'draft'; assert.equal(f.state.allowLeave('b'), false);
  f.get('notes').value = 'original'; assert.equal(f.state.allowLeave('b'), true);
  f.win.document.querySelector('.st-key-test').remove();
  await new Promise(resolve => f.win.setTimeout(resolve, 0));
  assert.equal(f.win.staffProSideEditor, undefined); f.cleanup();
});

test('checkbox mouse gesture prompts once and cancellation prevents mutation', () => {
  const f = fixture(); f.get('notes').value = 'draft';
  const down = () => f.get('toggle').dispatchEvent(new f.win.MouseEvent('mousedown', {bubbles:true,cancelable:true}));
  assert.equal(down(), false); assert.equal(f.get('toggle').checked, false);
  f.accept(); assert.equal(down(), true); f.get('toggle').click();
  assert.equal(f.prompts(), 2); assert.equal(f.get('toggle').checked, true); f.cleanup();
});

test('streaming the next bar never captures the previous form as its baseline', () => {
  const f = fixture(); f.get('notes').value = 'old draft';
  const next = install(f.win, {selector: '.st-key-test', identity: 'bar-b', barId: 'b'});
  assert.equal(next.baseline, null);
  f.get('notes').value = 'new bar';
  f.win.document.querySelector('[data-staffpro-form]').setAttribute('data-staffpro-form', 'bar-b');
  assert.equal(next.allowLeave('a'), true);
  assert.equal(f.prompts(), 0); f.cleanup();
});
