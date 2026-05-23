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
        
    # 1. Απόλυτα ασφαλής μετατροπή του exclude_ids σε καθαρή λίστα πεζών strings
    if exclude_ids is None: 
        safe_exclude_ids = []
    elif isinstance(exclude_ids, str):
        safe_exclude_ids = [exclude_ids.strip().lower()]
    else:
        safe_exclude_ids = [str(eid).strip().lower() for eid in exclude_ids]
        
    # 2. Ακριβής μετατροπή ώρας σε λεπτά (για να διαβάζει σωστά τα μεσάνυχτα/βράδια)
    def get_mins(t_str):
        try:
            h, m = map(int, str(t_str).strip()[:5].split(':'))
            # Αν η βάρδια είναι μέχρι τις 03:59, θεωρείται τμήμα της 24ωρης Gantt ημέρας
            if h < 4: 
                h += 24
            return h * 60 + m
        except:
            return 0
            
    new_s_mins = get_mins(t_start)
    new_e_mins = get_mins(t_end)
    
    # 3. Φιλτράρισμα Βαρδιών
    emp_assigns = [
        a for a in day_assignments 
        if str(a.get('employeeId')).strip() == str(employee_id).strip()
        and str(a.get('id', '')).strip().lower() not in safe_exclude_ids
        and not a.get('is_cancelled', False)
    ]
    
    for ea in emp_assigns:
        ea_s_mins = get_mins(ea.get('startTime', ''))
        ea_e_mins = get_mins(ea.get('endTime', ''))
        
        # 4. Έλεγχος Επικάλυψης με απόλυτα νούμερα (λεπτά) αντί για strings
        if new_s_mins < ea_e_mins and new_e_mins > ea_s_mins:
            # Επαναφορά της αρχικής σου λογικής: Επιτρέπει την επικάλυψη 
            # ΜΟΝΟ αν η νέα βάρδια λήγει ΜΕΤΑ την παλιά (χρήσιμο για handovers/αλλαγές)
            if new_e_mins > ea_e_mins:
                return t_start, t_end, False, "Allowed Overlap"
            else:
                return t_start, t_end, True, "Υπάρχει πλήρης χρονική επικάλυψη με άλλη βάρδια."
                
    return t_start, t_end, False, ""
