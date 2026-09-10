from odoo import http
from odoo.http import request
from datetime import datetime,date, timedelta
MAIN_TYPE = ('check_in_1','check_in_2','check_out_1','check_out_2','Auto add')
ENTRANCE_TYPE = ('turnstile_in','turnstile_out')
DUPLUCATE_INTERVAL = 5
class AttendancePortal(http.Controller):
    
    @http.route(['/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance(self, month=None, employee_type=None, **kw):

        # Default month = current month
        if not month:
            month = datetime.today().strftime("%Y-%m")
        start_day = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
        # last day of month
        if start_day.month == 12:
            end_day = date(start_day.year+1, 1, 1) - timedelta(days=1)
        else:
            end_day = date(start_day.year, start_day.month+1, 1) - timedelta(days=1)

        domain = []
        if employee_type:
            domain.append(('employee_type', '=', employee_type))

        employees = request.env['hr.employee'].sudo().search(domain)

        portal_data = {}
        for emp in employees:
            punches = self._fetch_punches(emp, day_from=start_day, day_to=end_day)
            main_punches = [p for p in punches if p['terminal_alias'] in ('check_in_1','check_in_2','check_out_1','check_out_2','Auto add')]
            entrance = [p['punch_time'] for p in punches if p['terminal_alias'] in ('turnstile_in','turnstile_out')]
            restaurant = next((p['punch_time'] for p in punches if p['terminal_alias']=='restaurant'), None)
            exceptions = self._detect_exceptions(emp, main_punches)

            for day in sorted({p['punch_time'][:10] for p in punches}):
                day_punches = [p['punch_time'] for p in main_punches if p['punch_time'].startswith(day)]
                day_entrance = [p for p in entrance if p.startswith(day)]
                day_restaurant = restaurant if restaurant and restaurant.startswith(day) else None
                key = (emp.id, day)
                portal_data[key] = {
                    'employee_id': emp.id,
                    'day': day,
                    'punches': day_punches,
                    'entrance_punches': day_entrance,
                    'restaurant': day_restaurant,
                    'exceptions': ", ".join(exceptions),
                    'buttons': ['delete','add_punch','add_leave','change_schedule'],
                }

        # Previous and next month for navigation
        prev_month = (start_day.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        next_month = (end_day + timedelta(days=1)).strftime("%Y-%m")
        # 🔹 sort by day (ascending)
        sorted_data = sorted(   
            portal_data.items(),
            key=lambda item: item[1]['day']
        )
        return request.render("nabi_hr.portal_attendance_template", {
            'portal_data':dict( sorted_data),
            'current_month': month,
            'prev_month': prev_month,
            'next_month': next_month,
        })

    def _fetch_punches(self, emp, day_from=None, day_to=None):
        # Call Zkbiotime API for this employee and day range
        # Return list of dicts with keys: punch_time, device_type, terminal_sn, terminal_alias
        return request.env['zk.biotime.connector'].sudo().get_punches(emp_code=emp.barcode, day_from=day_from, day_to=day_to)

    def _detect_exceptions(self, emp, punches):
        exceptions = []

        # duplicate detection (same device within 5 min)
        seen = {}
        for p in punches:
            
            emp_code = p["emp_code"]
            tid = p["id"]
            terminal = p["terminal_alias"]
            punch_time_str = p["punch_time"]
            punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")

            punch_day = punch_time.date()

            key = ( terminal, punch_day)
            
            if key in seen:
                delta = (punch_time - seen[key])
                if delta <= timedelta(minutes=DUPLUCATE_INTERVAL or 5):
                    exceptions.append(f"❌ Duplicate → ID {terminal}  | {punch_time_str} | Δ {delta}")
                    #delete_transaction(tid)
            else:
                print(f"✔️ Keeping punch → ID {tid} | Emp {emp_code} | {punch_time_str}")
                seen[key] = punch_time


                
           
        

            
        # missing main punches
        main_punches = [p for p in punches if terminal in MAIN_TYPE ]
        if len(main_punches) < 2:
            exceptions.append('missing_main')

        # missing restaurant for 6-14 usine
        if emp.employee_type=='worker':  # and emp.shift=='6-14'
            if not any(terminal=='restaurant' for p in punches):
                exceptions.append('missing_restaurant')

        return list(set(exceptions))