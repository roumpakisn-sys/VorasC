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
    Δέχεται το employee_id, ώρες έναρξης/λήξης και τις βάρδιες ΕΚΕΙΝΗΣ της ημέρας (day_assignments).
    Επιστρέφει: (adj_start, adj_end, is_conflict, message)
    """
    if not employee_id: 
        return t_start, t_end, False, ""
        
    if exclude_ids is None: 
        exclude_ids = []
        
    new_s = str(t_start)[:5]
    new_e = str(t_end)[:5]
    
    # Φιλτράρισμα: Κρατάμε μόνο τις βάρδιες του συγκεκριμένου υπαλλήλου, αγνοώντας όσες εξαιρούνται (π.χ. όταν κάνουμε edit)
    emp_assigns = [a for a in day_assignments if a['employeeId'] == employee_id and a['id'] not in exclude_ids]
    
    allowed_overlap = False
    for ea in emp_assigns:
        ea_s = str(ea['startTime'])[:5]
        ea_e = str(ea['endTime'])[:5]
        
        # Έλεγχος χρονικής επικάλυψης
        if new_s < ea_e and new_e > ea_s:
            if new_e > ea_e:
                # Επιτρέπεται μόνο αν η νέα βάρδια τελειώνει πιο αργά από την παλιά
                allowed_overlap = True
            else:
                return t_start, t_end, True, "Πλήρης επικάλυψη με υπάρχουσα βάρδια (δεν τελειώνει αργότερα)"
                
    return t_start, t_end, False, "Allowed Overlap" if allowed_overlap else ""
