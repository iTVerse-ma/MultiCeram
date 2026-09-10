from odoo import http,fields
from odoo.http import request
from datetime import datetime,date, timedelta
import requests

MAIN_TYPE = ('check_in_1','check_in_2','check_out_1','check_out_2',None)
ENTRANCE_TYPE = ('turnstile_in','turnstile_out','Auto add')
DUPLUCATE_INTERVAL = 5


class AttendancePortal(http.Controller):
    
    @http.route(['/my/attendances'], type='http', auth='user', website=True)
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
            exceptions = self._detect_exceptions( main_punches,emp)

            for day in sorted({p['punch_time'][:10] for p in punches}):
                day_punches = [p['punch_time'] for p in main_punches if p['punch_time'].startswith(day)]
                day_entrance = [p for p in entrance if p.startswith(day)]
                day_restaurant = restaurant if restaurant and restaurant.startswith(day) else None
                key = (emp.id, day)
                portal_data[key] = {
                    'employee_id': emp.id,
                    'emp_id': emp.id,
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
    # /my/attendance/add_punch
    @http.route(['/my/attendance/add_punch'], type='json', auth='user', website=True, methods=['POST'],crsf=False)
    def portal_add_punch(self, **kw):
        try:
            # Example: perform an action, e.g., mark attendance or send emails
            # Here we just simulate a process
            BASE_URL        = request.env['ir.config_parameter'].sudo().get_param('zk.server')
            USER            = request.env['ir.config_parameter'].sudo().get_param('zk.user')
            PASSWORD        = request.env['ir.config_parameter'].sudo().get_param('zk.password')
            AUTH            = (USER, PASSWORD)

            API = f"/att/api/manuallogs/"

            params = {
                'employee' 	: kw.get('employee'),
                'punch_time': kw.get('punch_time'),
                'punch_state':kw.get('punch_state'),
            }

            
            res = requests.post(f"{BASE_URL}{API}", auth=AUTH, json=params, timeout=60)
            
            if res.status_code != 200:
                return {'status': 'error', 'message': f"Failed to fetch punches: {res.text}"}
            return {f'status': 'success', 'message': f' attendance records deleted successfuly!\n {res.text}'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    


    @http.route(['/my/attendance/delete/<int:emp_id>'], type='json', auth='user', website=True, methods=['POST'])
    def portal_delete_punch(self, emp_id, **kw):
        try:
            # Example: perform an action, e.g., mark attendance or send emails
            # Here we just simulate a process
            BASE_URL        = request.env['ir.config_parameter'].sudo().get_param('zk.server')
            USER            = request.env['ir.config_parameter'].sudo().get_param('zk.user')
            PASSWORD        = request.env['ir.config_parameter'].sudo().get_param('zk.password')
            AUTH            = (USER, PASSWORD)

            API = f"/iclock/api/transactions/{emp_id}/"

            
            res = requests.delete(f"{BASE_URL}{API}", auth=AUTH, params={}, timeout=60)
            
            if res.status_code != 200:
                return {'status': 'error', 'message': f"Failed to fetch punches: {res.text}"}
            return {'status': 'success', 'message': f' attendance records deleted successfuly!'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    

    @http.route(['/my/attendances/<string:start_day>','/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance_day(self, start_day=None, end_day=None, employee_type=None, **kw):
    
       

        # Default month = current month
        if start_day:
            start_day = fields.Date.from_string(start_day) 
        else :
            start_day = datetime.today().date()
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        else:
            end_day = start_day 
        

        domain = []
        if employee_type:
            domain.append(('employee_type', '=', employee_type))

        employees = request.env['hr.employee'].sudo().search(domain)

        portal_data = {}
       
        punches         = self._fetch_punches( day_from=start_day,day_to=end_day)
        punches = [
            {k: d[k] for k in ("id", "punch_time", "terminal_alias", "emp_code","emp_id")}
            for d in punches
        ]

        main_punches    = [p for p in punches if p['terminal_alias'] in MAIN_TYPE]
        entrance        = [p for p in punches if p['terminal_alias'] in ENTRANCE_TYPE]
        restaurant      = [p for p in punches if p['terminal_alias']=='restaurant']
        

        for punch in punches:  #sorted({p['punch_time'][:10] for p in punches}):
            day = fields.Date.from_string(punch['punch_time'])
            key = (request.env["hr.employee"].search([('barcode','=',punch['emp_code'])],limit=1),day)
 
            portal_data.setdefault(key,{'emp_id' :punch['emp_id']})
 
            portal_data[key].setdefault('punches',[])
            day_punches = [p for p in main_punches if  p['id'] == punch['id'] ]
            portal_data[key]['punches'] += day_punches

            portal_data[key].setdefault('entrance_punches',[])
            day_entrance = [p for p in entrance if p['id'] == punch['id']]
            portal_data[key]['entrance_punches'] += day_entrance

            portal_data[key].setdefault('restaurant',[])
            day_restaurant = [p for p in restaurant if p['id'] == punch['id']]
            portal_data[key]['restaurant'] += day_restaurant

            portal_data[key].setdefault('exceptions',[])
            exceptions      = self._detect_exceptions(day_punches, punch['emp_code'])
            portal_data[key]['exceptions'] = exceptions


            portal_data[key]['buttons'] = {'delete' : True,
                                           'add_punch':True,
                                           'add_leave': True,
                                           'change_schedule':True
                
            }

        # Previous and next month for navigation
        prev_month = (start_day - timedelta(days=1)).strftime("%Y-%m-%d")
        next_month = (end_day + timedelta(days=1)).strftime("%Y-%m-%d")
        # 🔹 sort by day (ascending)
        # sorted_data = sorted(   
        #     portal_data.items(),
        #     key=lambda item: item[1]['day']
        # )
        return request.render("nabi_hr.portal_attendance_template", {
            'portal_data':portal_data,
            'current_month': start_day,
            'prev_month': prev_month,
            'next_month': next_month,
        })
    def _fetch_punches(self, emp=None, day_from=None, day_to=None):
        # Call Zkbiotime API for this employee and day range
        # Return list of dicts with keys: punch_time, device_type, terminal_sn, terminal_alias
        return request.env['zk.connector'].sudo().get_punches(emp_code=emp and emp.barcode or None, day_from=day_from, day_to=day_to)

    def _detect_exceptions(self,punches, emp=None):
        exceptions = []
        if emp  and   not isinstance(emp, type(request.env['hr.employee'])) :
            emp = request.env['hr.employee'].search([('barcode','=',emp)])
            

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
        if emp and emp.employee_type=='worker':  # and emp.shift=='6-14'
            if not any(terminal=='restaurant' for p in punches):
                exceptions.append('missing_restaurant')

        return list(set(exceptions))