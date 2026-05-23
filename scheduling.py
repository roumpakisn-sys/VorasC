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
    Επιστρέφει: (adj_start, adj_end, is_conflict, message)
    """
    if not employee_id: 
        return t_start, t_end, False, ""
        
    if exclude_ids is None: 
        exclude_ids = []
        
    # Μετατροπή των exclude_ids σε string για απόλυτη ασφάλεια (αποφυγή UUID object mismatches)
    safe_exclude_ids = [str(eid) for eid in exclude_ids]
        
    new_s = str(t_start)[:5]
    new_e = str(t_end)[:5]
    
    # Φιλτράρισμα: 
    # 1. Μόνο αυτού του υπαλλήλου
    # 2. ΑΓΝΟΟΥΜΕ τις βάρδιες που επεξεργαζόμαστε τώρα (safe_exclude_ids)
    # 3. ΑΓΝΟΟΥΜΕ τις ακυρωμένες βάρδιες (δεν πιάνουν χώρο στον χρόνο του υπαλλήλου)
    emp_assigns = [
        a for a in day_assignments 
        if str(a.get('employeeId')) == str(employee_id) 
        and str(a.get('id')) not in safe_exclude_ids
        and not a.get('is_cancelled', False)
    ]
    
    for ea in emp_assigns:
        ea_s = str(ea.get('startTime', ''))[:5]
        ea_e = str(ea.get('endTime', ''))[:5]
        
        # ΑΥΣΤΗΡΟΣ - ΣΥΜΜΕΤΡΙΚΟΣ Έλεγχος χρονικής επικάλυψης
        # Αν η νέα έναρξη είναι πριν την παλιά λήξη ΚΑΙ η νέα λήξη είναι μετά την παλιά έναρξη = ΕΠΙΚΑΛΥΨΗ
        if new_s < ea_e and new_e > ea_s:
            return t_start, t_end, True, "Υπάρχει χρονική επικάλυψη με άλλη βάρδια του υπαλλήλου."
                
    return t_start, t_end, False, ""
