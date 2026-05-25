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


def check_and_resolve_conflict(employee_id, t_start, t_end, day_assignments, exclude_ids=None):
    """
    Pure Function: Ελέγχει αν υπάρχει χρονική επικάλυψη (conflict) στις βάρδιες.

    Κανόνας επιτρεπτής επικάλυψης:
    Αν δύο εργασίες του ίδιου υπαλλήλου επικαλύπτονται χρονικά, επιτρέπεται η επικάλυψη
    μόνο όταν η μία εργασία τελειώνει αργότερα από την άλλη.

    Παράδειγμα:
    - Εργασία 1: 10:00-12:00
    - Εργασία 2: 10:00-13:00

    Αυτό πρέπει να επιτρέπεται ανεξάρτητα από τη σειρά καταχώρησης:
    είτε μπει πρώτα το 10:00-12:00 είτε μπει πρώτα το 10:00-13:00.

    Δεν επιτρέπεται όταν οι δύο επικαλυπτόμενες εργασίες έχουν ίδια ώρα λήξης,
    γιατί τότε δεν υπάρχει ξεκάθαρη "μετά την άλλη" εργασία.
    """
    if not employee_id:
        return t_start, t_end, False, ""

    if exclude_ids is None:
        exclude_ids = []

    new_s = str(t_start)[:5]
    new_e = str(t_end)[:5]

    # Κρατάμε μόνο τις βάρδιες του συγκεκριμένου υπαλλήλου,
    # αγνοώντας όσες εξαιρούνται, π.χ. όταν κάνουμε edit υπάρχουσας μπάρας.
    emp_assigns = [
        a for a in day_assignments
        if a.get('employeeId') == employee_id and a.get('id') not in exclude_ids
    ]

    allowed_overlap = False

    for ea in emp_assigns:
        ea_s = str(ea.get('startTime', ''))[:5]
        ea_e = str(ea.get('endTime', ''))[:5]

        # Χρονική επικάλυψη υπάρχει όταν η νέα έναρξη είναι πριν από την παλιά λήξη
        # και η νέα λήξη είναι μετά από την παλιά έναρξη.
        if new_s < ea_e and new_e > ea_s:
            # Επιτρέπεται αν οι λήξεις είναι διαφορετικές.
            # Έτσι το 10-12 + 10-13 επιτρέπεται και στις δύο σειρές καταχώρησης.
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
