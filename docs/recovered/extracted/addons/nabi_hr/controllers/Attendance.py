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
    

    @http.route(['/my/attendance/<string:start_day>','/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance_day(self, start_day=None, end_day=None, employee_type=None, **kw):
        return request.render('nabi_hr.portal_attendance_template')

    @http.route(['/my/attendance/json/<string:start_day>','/my/attendance/json'], type='json', auth='user',methods=['POST'], website=True,csrf=False)
    def portal_attendance_json(self, start_day=None, end_day=None, employee_type=None,page=1, page_size=10 ,**kw):
    

        # Default month = current month
        if start_day:
            start_day = fields.Date.from_string(start_day) 
        else :
            start_day = datetime.today().date()
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        else:
            end_day = start_day 
        

        # if employee_type:
        #     domain.append(('employee_type', '=', employee_type))

        domain = [('punch_time','>=',start_day),('punch_time','<=',end_day)]
        # employees = request.env['hr.employee'].sudo().search(domain)

        portal_data = {}
        offset=(page-1) * page_size
        limit=page_size
        punches         = request.env['zk.transaction'].search(domain,).sorted(key=lambda x:(x.employee_id.barcode.zfill(6)))[offset:limit+offset]
        
        #,["id","tid", "punch_time", "terminal_alias", "emp_code","emp"])
        # punches = [
        #     {k: d[k] for k in ("id", "punch_time", "terminal_alias", "emp_code","emp_id")}
        #     for d in punches
        # ]

        main_punches    = punches.filtered(lambda x:x.usage == 't').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])#[p for p in punches if p['terminal_alias'] in MAIN_TYPE]
        entrance        = punches.filtered(lambda x:x.usage == 'p').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])# [p for p in punches if p['terminal_alias'] in ENTRANCE_TYPE]
        restaurant      =  punches.filtered(lambda x:x.usage == 'r').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])# [p for p in punches if p['terminal_alias']=='restaurant']
        

        for punch in punches:  #sorted({p['punch_time'][:10] for p in punches}):
            day         = fields.Date.from_string(punch['punch_time']).strftime('%Y-%d-%m')
            employee_id = request.env["hr.employee"].search([('barcode','=',punch['emp_code'])],limit=1)
            key         = employee_id.id
 


            portal_data.setdefault(day,{})
            portal_data[day].setdefault(key ,{})
            portal_data[day][key].setdefault('emp_id',punch['emp'])
            portal_data[day][key].setdefault('employee_id',employee_id and employee_id.read(['barcode','name'])[0])



            portal_data[day][key].setdefault('punches',[])
            day_punches = [p for p in main_punches if  p['tid'] == punch['tid'] ]

            portal_data[day][key].setdefault('entrance_punches',[])
            day_entrance = [p for p in entrance if p['tid'] == punch['tid']]
            

            portal_data[day][key].setdefault('restaurant',[])
            day_restaurant = [p for p in restaurant if p['tid'] == punch['tid']][:1]

            portal_data[day][key].setdefault('exceptions',[])
            
            
            portal_data[day][key]['punches']             += day_punches
            portal_data[day][key]['entrance_punches']    += day_entrance
            portal_data[day][key]['restaurant']          += day_restaurant
            
            

            portal_data[day][key]['buttons'] = {'delete' : True,
                                           'add_punch':True,
                                           'add_leave': True,
                                           'change_schedule':True
                
            }

        new_portal_data = portal_data.copy() or {}
        for pkey,pval in portal_data.items():
            pvals = pval.copy()
            for key,data in pvals.items():
                # key         = pdata[0]
                # data        = pdata[1]
                day_punches     = portal_data[pkey][key]['punches']            
                day_entrance    = portal_data[pkey][key]['entrance_punches']   
                day_restaurant  = portal_data[pkey][key]['restaurant'][:1] 
                new_portal_data[pkey][key]['restaurant'] = day_restaurant

                print (f"####### {day_punches}")        
                
                exceptions , day_punches     = self._detect_exceptions(day_punches[:])#, punch['emp_code'])

                new_portal_data[pkey][key]['exceptions'] = exceptions
                new_portal_data[pkey][key]['punches'] = day_punches
                
                if day_entrance:
                    exceptions , day_entrance     = self._detect_exceptions(day_entrance[:])#, punch['emp_code'])
                    new_portal_data[pkey][key]['exceptions'] += exceptions
                    new_portal_data[pkey][key]['entrance_punches'] = day_entrance


                if not new_portal_data[pkey][key]['exceptions']:
                    new_portal_data[pkey].pop(key)

        
        portal_data = new_portal_data


        # new_portal_data = portal_data.copy() or {}
        # for pdata in portal_data.items():
        #     key         = pdata[0]
        #     data        = pdata[1]
        #     day_punches     = portal_data[key]['punches']            
        #     day_entrance    = portal_data[key]['entrance_punches']   
        #     day_restaurant  = portal_data[key]['restaurant'][:1] 
        #     new_portal_data[key]['restaurant'] = day_restaurant

        #     print (f"####### {day_punches}")        
            
        #     exceptions , day_punches     = self._detect_exceptions(day_punches[:])#, punch['emp_code'])

        #     new_portal_data[key]['exceptions'] = exceptions
        #     new_portal_data[key]['punches'] = day_punches
            
        #     if day_entrance:
        #         exceptions , day_entrance     = self._detect_exceptions(day_entrance[:])#, punch['emp_code'])
        #         new_portal_data[key]['exceptions'] += exceptions
        #         new_portal_data[key]['entrance_punches'] = day_entrance


        #     if not new_portal_data[key]['exceptions']:
        #         new_portal_data.pop(key)

        
        # portal_data = new_portal_data


        # Previous and next month for navigation
        prev_month = (start_day - timedelta(days=1)).strftime("%Y-%m-%d")
        next_month = (end_day + timedelta(days=1)).strftime("%Y-%m-%d")
        # 🔹 sort by day (ascending)
        # sorted_data = sorted(   
        #     portal_data.items(),
        #     key=lambda item: item[1]['day']
        # )

        return  {
            'portal_data'   : [list(v.values()) for k,v in portal_data.items()],
            'current_month' : start_day,
            'prev_month'    : prev_month,
            'next_month'    : next_month,
        }
    
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
        for p in sorted(punches[:] ,key=lambda x:x["punch_time"]) :
            
            emp_code    = p["emp_code"]
            tid         = p["id"]
            terminal    = p["terminal_alias"]
            punch_time  = p["punch_time"]
            # punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")

            punch_day = punch_time.date()

            key = ( terminal, punch_day)
            
            if key in seen:
                delta = (punch_time - seen[key])
                if delta <= timedelta(minutes=DUPLUCATE_INTERVAL or 5):
                    #exceptions.append(f"❌ Duplicate → {terminal} | {punch_time}")
                    punches.remove(p)
                    #delete_transaction(tid)
            else:
                #print(f"✔️ Keeping punch → ID {tid} | Emp {emp_code} | {punch_time}")
                seen[key] = punch_time

        # missing main punches
        #main_punches = [p for p in punches if terminal in MAIN_TYPE ]
        if len(punches) < 2:
            exceptions.append(f'missing_main ')

        # # missing restaurant for 6-14 usine
        # if emp and emp.employee_type=='worker':  # and emp.shift=='6-14'
        #     if not any(terminal=='restaurant' for p in punches):
        #         exceptions.append('missing_restaurant')

        return list(set(exceptions)),punches