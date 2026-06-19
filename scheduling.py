def is_on_leave(employee_id, check_date, leaves_by_emp):
    """
    Pure Function: Ελέγχει αν ένας υπάλληλος έχει άδεια τη συγκεκριμένη ημερομηνία.
    Δέχεται το employee_id, την ημερομηνία και το λεξικό με τις άδειες όλων των υπαλλήλων.
    """
    if not employee_id:
        return False

    emp_leaves = leaves_by_emp.get(employee_id, [])
    for l in emp_leaves:
        if l['startDate'] <= check_date <= l['endDate']:
            return True

    return False


def _normalize_time(value):
    """
    Επιστρέφει ώρα σε μορφή HH:MM ώστε οι συγκρίσεις να είναι σταθερές.
    Δέχεται τιμές τύπου '09:00', '09:00:00', time κ.λπ.
    """
    if value is None:
        return ""

    return str(value)[:5]


def check_and_resolve_conflict(employee_id, t_start, t_end, day_assignments, exclude_ids=None):
    """
    Pure Function: Ελέγχει αν υπάρχει χρονική επικάλυψη (conflict) στις βάρδιες.

    Κανόνας επιτρεπτής επικάλυψης:
    Αν δύο εργασίες του ίδιου υπαλλήλου επικαλύπτονται χρονικά, επιτρέπεται
    όταν έχουν διαφορετική ώρα λήξης.

    Αυτό επιτρέπει και τις δύο σειρές καταχώρησης:

    Παράδειγμα Α:
    - Πρώτα: 10:00-12:00
    - Μετά:  10:00-13:00
    Επιτρέπεται. Η μπάρα 10:00-13:00 εμφανίζεται ως "ΜΕΤΑ ΑΠΟ".

    Παράδειγμα Β:
    - Πρώτα: 10:00-13:00
    - Μετά:  10:00-12:00
    Επιτρέπεται. Το Gantt, όταν ξαναχτιστεί, θα δείξει πάλι τη μπάρα
    10:00-13:00 ως "ΜΕΤΑ ΑΠΟ" την 10:00-12:00.

    Δεν επιτρέπεται όταν οι δύο επικαλυπτόμενες εργασίες έχουν ίδια ώρα λήξης,
    γιατί τότε δεν υπάρχει ξεκάθαρα ποια είναι η "μετά από" εργασία.
    """
    if not employee_id:
        return t_start, t_end, False, ""

    if exclude_ids is None:
        exclude_ids = []

    new_s = _normalize_time(t_start)
    new_e = _normalize_time(t_end)

    # Κρατάμε μόνο τις βάρδιες του συγκεκριμένου υπαλλήλου,
    # αγνοώντας όσες εξαιρούνται, π.χ. όταν κάνουμε edit υπάρχουσας μπάρας.
    emp_assigns = [
        a for a in day_assignments
        if a.get('employeeId') == employee_id and a.get('id') not in exclude_ids
    ]

    allowed_overlap = False

    for ea in emp_assigns:
        ea_s = _normalize_time(ea.get('startTime', ''))
        ea_e = _normalize_time(ea.get('endTime', ''))

        # Χρονική επικάλυψη υπάρχει όταν η νέα έναρξη είναι πριν από την παλιά λήξη
        # και η νέα λήξη είναι μετά από την παλιά έναρξη.
        if new_s < ea_e and new_e > ea_s:
            # Επιτρέπεται αν οι λήξεις είναι διαφορετικές.
            # Έτσι το 10-12 + 10-13 επιτρέπεται ανεξάρτητα από τη σειρά καταχώρησης.
            if new_e != ea_e:
                allowed_overlap = True
            else:
                return (
                    t_start,
                    t_end,
                    True,
                    "Πλήρης επικάλυψη με υπάρχουσα βάρδια (ίδια ώρα λήξης)"
                )

    return t_start, t_end, False, "Allowed Overlap" if allowed_overlap else ""
