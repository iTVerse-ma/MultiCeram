from odoo import http,fields,_
from odoo.tools import format_date
from odoo.http import request
from odoo.exceptions import UserError
from datetime import datetime,date, timedelta
import requests
import logging
from dateutil.relativedelta import relativedelta
_logger = logging.getLogger(__name__)
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs


MAIN_TYPE = ('check_in_1','check_in_2','check_out_1','check_out_2',None)
ENTRANCE_TYPE = ('turnstile_in','turnstile_out','Auto add')
DUPLUCATE_INTERVAL = 30


from collections import namedtuple

class DotDict(dict):
    def __getattr__(self, key):
        value = self.get(key)
        if isinstance(value, dict):
            return DotDict(value)
        if isinstance(value, list):
            return [DotDict(v) if isinstance(v, dict) else v for v in value]
        return value

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

def dotify(obj):
    if isinstance(obj, dict):
        return DotDict({k: dotify(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [dotify(i) for i in obj]
    return obj


# Create a custom logger
logger = logging.getLogger(__name__ + ".simple")

# Prevent propagation to Odoo root logger (VERY important)
logger.propagate = False

# Set level
logger.setLevel(logging.INFO)

# Create handler with your custom format (only message)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)

# Avoid adding handlers twice (odoo reload issues)
if not logger.handlers:
    logger.addHandler(handler)



class AttendancePortal(http.Controller):
    

    @http.route(['/my/employee/update',], type='http', auth='user', website=True,methods=['POST'],csrf=False)
    def portal_employee_update(self, *args,**kw):
        referer = request.httprequest.headers.get('Referer')
        message = None
        url_parts           = list(urlparse(referer))
        query               = parse_qs(url_parts[4])  # url_parts[4] = query
       
        if 'terminal_ids' in kw:
            query['terminal_ids']   = kw.pop('terminal_ids') 
        if 'start_date' in kw:
            query['start_date'] = kw.pop('start_date')
        if 'end_date' in kw:
            query['end_date']   = kw.pop('end_date')
        if 'emp_id' in kw:
            query['emp_id']     = kw.pop('emp_id')
        
        if 'parent_id' in kw and kw.get('parent_id'):
            kw['parent_id'] = int(kw.get('parent_id'))
        if 'coach_id' in kw and kw.get('coach_id'):
            kw['coach_id'] = int(kw.get('coach_id'))
        
        try:
            if kw:
                employee_id = int( kw.pop('employee_id'))
                
                res = request.env['hr.employee'].browse(employee_id).write(kw)

                if res:
                    message = 'Employé mis à jours avec succés !'
                else:
                    message = 'Mise à jour échoué!'
        except Exception as e:
            message = f'{e}'
        
        
        query['message']    = kw.pop('message', f'Formulaire envoyé !\n {message} ')
        url_parts[4]        = urlencode(query, doseq=True)
        new_url             = urlunparse(url_parts)
        return request.redirect(new_url)

        



    @http.route(['/my/attendance/report','/my/attendance/report/<string:emp_id>'], type='http', auth='user', website=True)
    def portal_my_report(self, start_day=None, end_day=None, emp_id=None,date=None ,**kw):

        if start_day:
            start_day = fields.Date.from_string(start_day) 
        elif date :
            start_day = fields.Date.from_string(date).replace(day=1)
        else:
            start_day = datetime.today().date().replace(day=1)
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        elif date:
            end_day =  start_day + relativedelta(months=1,days=-1)
        else:
            end_day = start_day 

        domain = [('duplicate','=',False),('to_delete','=',False),('punch_time','>=',start_day),('punch_time','<=',end_day)]
        try:
            emp_id = int(emp_id)
            domain += [('employee_id','=',emp_id)]
        except:
            emp_id = 0
            pass
        
        SHIFT_DEFINITIONS = [
            {"name": "Poste 1", "start": 6, "end": 14},
            {"name": "Poste 2", "start": 14, "end": 22},
            {"name": "Poste 3", "start": 22, "end": 6, "overnight": True},
            {"name": "Normal", "start": 8, "end": 18, "pause": 1},
        ]

        def get_closest_shift(check_time: datetime):
            best_shift = None
            min_diff = timedelta(hours=24)
            for shift in SHIFT_DEFINITIONS:
                shift_start = check_time.replace(hour=shift["start"], minute=0, second=0)
                if shift.get("overnight"):
                    shift_end = shift_start + timedelta(hours=(24 - shift["start"] + shift["end"]))
                else:
                    shift_end = shift_start + timedelta(hours=(shift["end"] - shift["start"]))
                diff = abs((check_time - shift_start).total_seconds())
                if diff < min_diff.total_seconds():
                    min_diff = timedelta(seconds=diff)
                    best_shift = shift["name"]
            return best_shift

        record = request.env['zk.transaction'].sudo().search(domain).filtered(lambda x:x.terminal_id.usage=='t')
        if not record.exists():
            pass
            #return request.not_found()
        report_ref =request.env.ref('nabi_hr.action_report_transaction_report',False)
        # return the report as PDF
        pdf,dummy = request.env.ref('nabi_hr.action_report_transaction_report')._render_qweb_pdf(report_ref, 
                                            record.ids,data={'docs': record,
                                                             'end_date' :end_day, 
                                                             'start_date':start_day,
                                                             'poste':get_closest_shift})

        pdfhttpheaders = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', f'inline; filename=rapport"{start_day}-{end_day}-{emp_id}.pdf"')
        ]
        return request.make_response(pdf, headers=pdfhttpheaders)

    @http.route('/my/transaction/copy/<int:transaction_id>', type='json', auth='user', website=True, methods=['POST','GET'],csrf=False)
    def portal_transaction_copy(transaction_id, **kw):
        try:
            request.env['zk.transaction'].browse(transaction_id).copy({'tid ':None, 'terminal_sn':None, 'terminal_alias':None})
            return  {'status': 'success', 'message': 'Transaction copié'}
        except Exception as e:
            return  {'status': 'success', 'message': str(e)}
        

    @http.route(['/my/attendance/get_punch_stacked','/my/attendance/get_punch_stacked/<string:emp_id>'], type='http', auth='user', website=True, methods=['POST','GET'],csrf=False)
    def portal_get_punch_stacked(self, start_day = None, end_day=None, emp_id=0,terminal_ids=[],**kw):
        
        def roundTo30(dt, minutes=30, mode="proche"):
            """
            dt : datetime
            minutes : tranche d'arrondi (5, 10, 15, 30, 60…)
            mode : "up", "down", "proche"
            """

            # total minutes since midnight
            total_min = dt.hour * 60 + dt.minute
            step = minutes

            if mode == "proche":   # round to nearest
                rounded = round(total_min / step) * step

            elif mode == "up":     # ceil
                rounded = -(-total_min // step) * step

            elif mode == "down":   # floor
                rounded = (total_min // step) * step

            else:
                raise ValueError("mode must be 'up', 'down' or 'proche'")

            # reconstruct datetime
            return dt.replace(
                hour=rounded // 60,
                minute=rounded % 60,
                second=0,
                microsecond=0
            )
        def roundTo20(dt: datetime, mode="proche") -> datetime:
            minutes = dt.minute
            hours = dt.hour
            if mode =='up':
                if minutes <= 9:
                    return dt.replace(minute=0, second=0, microsecond=0)

                elif minutes <= 30:
                    return dt.replace(minute=30, second=0, microsecond=0)

                else:  # 45 à 59
                    # ajouter 1h puis remettre minutes=0
                    return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

            if minutes <= 19:
                
                return dt.replace(minute=0, second=0, microsecond=0)

            elif minutes <= 44:
                
                return dt.replace(minute=30, second=0, microsecond=0)

            else:  # 45 à 59
                # ajouter 1h puis remettre minutes=0
                return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        # init totals
        worked_day        = 0
        jr_absence        = 0
        jr_presence       = 0
        total_normal      = timedelta()
        total_normal2     = timedelta()
        total_pause       = timedelta()
        total_abs         = timedelta()
        total_hs          = timedelta()
        total_hs_corrige  = timedelta()
        total_hs_declare  = timedelta()
        total_hs25        = timedelta()
        total_hs50        = timedelta()
        total_hs100       = timedelta()
        total_conge       = timedelta()
        total_jf          = timedelta()
        total_jr          = timedelta()

        employee = request.env['hr.employee'].search([('active','in',(True,False)),('barcode','=',emp_id)])

        if start_day:
            start_day = fields.Date.from_string(start_day) 
        else :
            start_day = datetime.today().date() + relativedelta(months=-1)
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        else:
            end_day = datetime.today().date()

       
        
        domain = [('duplicate','=',False),('to_delete','=',False),('punch_time','>=',start_day),('punch_time','<=',end_day),('emp_code','=',emp_id)]

        
            
        
        if terminal_ids:
            terminal_ids = list(map(int,terminal_ids.split(',')))

            terminal_domain = domain +  ['|',('terminal_id','=',False),('terminal_id','in',terminal_ids)]

        else:
            terminal_ids = request.env['zk.terminals'].search( [('usage','in',('t',False))]).ids
        
        punches         = request.env['zk.transaction'].search(domain,order='punch_time desc')
        if employee.x_ignore_uhf:
            punches = punches.filtered(lambda x:x.terminal_id != request.env.ref('nabi.uhf'))
        
        # delete duplicate
        seen = {}
        for p in punches.sorted('punch_time'):
            key = (p.emp_code,p.terminal_id.usage, p.punch_time.date())
            #print(f"🚩  seen : {seen}")
            
            if key in seen:
                delta = (p.punch_time - seen[key])
                logger.info(f"\t 🚩 delta : {delta} = {p.punch_time} - { seen[key]}")
                if delta <= timedelta(minutes = 5):
                    logger.info(f"\t\t  🚩 duplicated")
                    p.duplicate = True

            seen[key] = p.punch_time

        # jours férier
        jf =  request.env['resource.calendar.leaves'].search([('resource_id','=',False),
                                                              '|','&',('date_from','>=',start_day),('date_from','<=',end_day),
                                                              '&',('date_to','>=',start_day),('date_to','<=',end_day)])

        # congé 
        conges = request.env['hr.leave'].search([('employee_id.barcode','=',emp_id)])
        
        # grouper par Date range
        dgroupeds = {}
        for n in range((end_day - start_day).days + 1):
            jour = start_day + timedelta(n)
            dgrouped  =  punches.filtered(lambda x:(x.x_date_appliquee or x.punch_time.date())==jour).sorted('punch_time')
            dgroupeds = {**dgroupeds,jour:dgrouped}
            jr_presence+=1
        
        
        # compute values
        pgrouped_index = 0
        pgroupeds = {}
        to_skip = request.env['zk.transaction'].browse(0)
        # raise UserWarning(dgroupeds)
        dgroupeds_items = list(dgroupeds.items())
        for dgrouped in dgroupeds_items:
            jour,data = dgrouped
            data = data - to_skip
            to_skip = request.env['zk.transaction'].browse(0)

            try:
                pgrouped1 = dgroupeds_items[pgrouped_index+1:pgrouped_index+2] or []
            except Exception as e:
                raise UserWarning(f'{dgroupeds_items}\n {e}')
            
            if pgrouped1 and pgrouped1[0] and pgrouped1[0][1] and (len(data)==1  and  data.sens=='in') or ( data[:1].sens=='out' and data[-1:].sens=='in' ):
                for p1 in pgrouped1[0][1]:
                    if p1.sens =='out':
                        to_skip = to_skip | p1
                    else:
                        break
            
            data = data | to_skip
            
            clean_punches   = data - (data[:1] if data[:1].sens=='out' else data[-1:] if data[-1:].sens=='in' else data.browse(0) )
            pause           = clean_punches[1:-1].filtered(lambda x:x.usage=='p')
            presence        = clean_punches.filtered(lambda x:x.usage in ('t',False))
            restau          = clean_punches.filtered(lambda x:x.usage=='r')
            worked_day      = worked_day+1 if data else  worked_day

            # Calcul d'anomalie
            anomalies         = []
            anomalie_presence = []
            if presence and len(presence)%2 > 0:
                anomalies.append({'code':'t','message':' 🚩 Pointage de présence impaire'})
                anomalie_presence.append({'code':'t','message':' 🚩 Pointage de présence impaire'})
            
            if pause and len(pause)%2 > 0:
                anomalies.append({'code':'p','message':' 🚪 Pointage de porte impaire'})

            if not presence and data :
                anomalies.append({'code':'p','message':' 👮‍♂️ Détecté présent'})
            
            

            is_holiday      = jf and jf.filtered(lambda x: jour >= x.date_from.date() and jour <= x.date_to.date()  )  or jf.browse(0)
            is_conge        = conges.filtered(lambda x:dgrouped[0] >= x.request_date_from and jour <= x.request_date_to)
            jr              = request.env['x_jour_repos'].search([('x_employee_id','=',employee.id),('x_date','=',jour)])
            heure_normal    = timedelta(hours=employee.x_day_hour or 8)
            

            heures_pause = timedelta()
            # heures_pause    = not anomalies and employee.x_pause and timedelta(hours=1) or ((pause[-1:].punch_time.replace(second=0) - pause[:1].punch_time.replace(second=0)) if len(pause)>=2 else timedelta(hours=1) if pause or restau else timedelta())
            if not anomalie_presence  and presence:
                if  employee.x_pause or pause:
                    heures_pause    = timedelta(hours=1) 
                elif restau:
                    if presence[:1].punch_time < restau.punch_time < presence[-1:].punch_time:
                        heures_pause    = timedelta(hours=1) 
                    if timedelta() < (restau.punch_time  - presence[:1].punch_time) < timedelta(minutes=15):
                        heures_pause    = timedelta(hours=0) 
                    if timedelta() < (presence[-1:].punch_time - restau.punch_time) < timedelta(minutes=15) :
                        heures_pause    = timedelta(hours=0) 
                        
                        
                    
        
            #Samedi demi journées:
            if employee.x_horaire == 'normal' and jour.weekday()==5:
                heure_normal = timedelta(hours=4) if employee.x_workedday_week == 44 else timedelta(hours=8)
                heures_pause = timedelta()

            #dimanche pour les Normaux:
            if employee.x_horaire == 'normal' and jour.weekday()==6:
                heure_normal = timedelta(hours=8)
                heures_pause = timedelta()

            
            heures          = not anomalie_presence and (((clean_punches[-1:].punch_time.replace(second=0) - roundTo30(clean_punches[:1].punch_time,mode='proche').replace(second=0)) if clean_punches else timedelta()) ) or timedelta()
            heures25        = not anomalie_presence and (((roundTo20(clean_punches[-1:].punch_time).replace(second=0) - roundTo30(clean_punches[:1].punch_time,mode='proche').replace(second=0)) if clean_punches else timedelta())  ) or timedelta()
            
            if employee.x_horaire == 'normal' and heures25 >= timedelta(hours=5):
                heures          = heures   - heures_pause 
                heures25        = heures25 - heures_pause 
            elif employee.x_horaire == 'normal':
                heures_pause  = timedelta()

            
            
            hs              =  (heures   ) - (heure_normal + heures_pause)   if heures       > (heure_normal + heures_pause) else timedelta()
            hs25            =  (heures25 ) - (heure_normal + heures_pause)   if heures       > (heure_normal + heures_pause) else timedelta()
            abs25           =   heure_normal - heures25     if heure_normal > heures25     else timedelta()
            


            total_normal    += heures
            total_normal2   += heures25
            total_pause     += heures_pause
            total_abs       += abs25
            total_hs        += hs
            total_hs25      += hs25
            total_hs_corrige+= hs25 if hs25 > timedelta() else timedelta()
            total_hs_declare+= timedelta(hours=jr.x_hs_corrige)

            total_hs25      += timedelta(hours=jr.x_hs_25) 
            total_hs50      += timedelta(hours=jr.x_hs_50) 
            total_hs100     += timedelta(hours=jr.x_hs_100) 
            jr_absence      += 1 if not data else 0
            
            filter_by_terminal = lambda x:x.filtered(lambda x:(x.terminal_id.id in terminal_ids or not x.terminal_id) if terminal_ids else True).sorted('punch_time')
 
            jour_data = {
                'all_punches'   : filter_by_terminal(data),
                'clean_punches' : filter_by_terminal(clean_punches),
                'pause'         : filter_by_terminal(pause),
                'presence'      : presence.filtered(lambda x:(x.terminal_id.id in terminal_ids or not x.terminal_id)  if terminal_ids else True).sorted('punch_time'),
                'restau'        : filter_by_terminal(restau),
                'anomalies'     : anomalies,
                "heures_pause"  : heures_pause,
                "heures"        : heures,
                "heures25"      : heures25,
                "hs"            : hs,
                "hs25"          : hs25 if hs25 > timedelta() else timedelta(),
                "hs50"          : heures25 if  heures25 > timedelta() and employee.x_horaire == 'normal' and jour.weekday()==6  else timedelta(),
                
                "abs25"         : abs25, 


                'jr'            : jr,
                'is_holiday'    : is_holiday,
                "is_conge"      : is_conge,

            }

            pgroupeds = {**pgroupeds,jour:jour_data}
            pgrouped_index = pgrouped_index+1

        # pgroupeds = list(pgroupeds.items())
        Pair =  namedtuple('Pair', ['jour', 'value'])
        pgroupeds  = [Pair(k, dotify(v)) for k, v in pgroupeds.items()]
       
        




        return request.render("nabi_hr.portal_punch_stacked_template", dotify({
            'format_date'   : lambda x:format_date(request.env,value=x,lang_code='fr_FR',date_format='EEE').capitalize(),
            '_'             : _,
            'roundTo20'     : roundTo20,
            'roundTo30'     : roundTo30,
            'terminals'     : request.env['zk.terminals'].search([]), 
            'portal_punches': punches,
            'emp_id'        : emp_id,
            'start_day'     : start_day,
            'end_day'       : end_day,
            'terminal_ids'  : terminal_ids,
            "kw"            : kw,
            "domain"        : domain,
            "jf"            : jf,
            "employee"      : employee,
            "emp_zkid"      : employee.zk_id,
            "conges"        : conges,
            "pgroupeds"     :pgroupeds,
            #totals
            "worked_day"        :worked_day,
            "jr_absence"        :jr_absence,
            "jr_presence"       :jr_presence,
            "total_normal"      :total_normal,
            "total_normal2"     :total_normal2,
            "total_pause"       :total_pause,
            "total_abs"         :total_abs,
            "total_hs"          :total_hs,
            "total_hs_corrige"  :total_hs_corrige,
            "total_hs_declare"  :total_hs_declare,
            "total_hs25"        :total_hs25,
            "total_hs50"        :total_hs50,
            "total_hs100"       :total_hs100,
            "total_conge"       :total_conge,
            "total_jf"          :total_jf,
            "total_jr"          :total_jr,





            
        }))

    @http.route(['/my/attendance/get_punches','/my/attendance/get_punches/<string:emp_id>'], type='http', auth='user', website=True, methods=['POST','GET'],csrf=False)
    def portal_get_punches(self, start_day = None, end_day=None, emp_id=0,terminal_ids=None,**kw):
        
        # Default month = current month
        if start_day:
            start_day = fields.Date.from_string(start_day) 
        else :
            start_day = datetime.today().date()
        
        if end_day:
            end_day = fields.Date.from_string(end_day) 
        else:
            end_day = start_day 

        try:
            emp_id = int(emp_id)
        except:
            emp_id = None
            pass
            
        
        domain = [('duplicate','=',False),('to_delete','=',False),('punch_time','>=',start_day),('punch_time','<=',end_day),('employee_id','=',emp_id)]
        
        if terminal_ids:
            terminal_ids = list(map(int,terminal_ids.split(',')))

            domain += [('terminal_id','in',terminal_ids)]
        #_logger.info(f"❤️ domaine {domain}\n {terminal_ids}")
        # employees = request.env['hr.employee'].sudo().search(domain)

        portal_data = {}
        # offset=(page-1) * page_size
        # limit=  page_size
        punches         = request.env['zk.transaction'].search(domain,order='punch_time desc')
        #_logger.info(f"❤️⬇ Punches {punches}")


        return request.render("nabi_hr.portal_punches_template", {
            'terminals': request.env['zk.terminals'].search([]), 
            'portal_punches' : punches,
            'emp_id':emp_id,
            'start_day':start_day,
            'end_day':end_day,
            "kw":kw,
            "domain" : domain

            
        })


    @http.route(['/my/attendance/add_jour_repos'], type='json', auth='user', website=True, methods=['POST'],csrf=False)
    def portal_add_jour_repos(self, **kw):
        
        if  kw.get('employee',False) and  kw.get('date',False):
            employee = request.env['hr.employee'].search([('zk_id','=',kw.get('employee'))],limit=1)
        else:
            return {'status':'Error', 'message':f'Employe ou date invalide :{kw}'}
        hs = None
        if 'hs' in kw and kw.get('hs',False):
            sec = float(kw.get('hs',False))
            hs  =  sec and sec/3600 or False
            
        

        jr = request.env['x_jour_repos']
        existing  = jr.search([('x_employee_id','=',employee.id),('x_date','=',kw.get('date',False))])
        if existing:
            existing.x_jour_repos = True if kw.get('mode','') == 'add' else False
            existing.x_hs = hs or False 
            return {'status':'success', 'message':f'Enregistré 1 {hs}'}
        else:
            jr.create({'x_employee_id':employee.id,
                       'x_date': kw.get('date'),
                       'x_jour_repos' : True if kw.get('mode') == 'add' else False
                        })
            return {'status':'success', 'message':f'Enregistré 2' }


    @http.route(['/my/attendance/add_punch'], type='json', auth='user', website=True, methods=['POST'],csrf=False)
    def portal_add_punch(self, **kw):
        try:
            # Example: perform an action, e.g., mark attendance or send emails
            # Here we just simulate a process
            BASE_URL        = request.env['ir.config_parameter'].sudo().get_param('zk.server')
            USER            = request.env['ir.config_parameter'].sudo().get_param('zk.user')
            PASSWORD        = request.env['ir.config_parameter'].sudo().get_param('zk.password')
            AUTH            = (USER, PASSWORD)

            API = f"att/api/manuallogs/"

            params = {
                'employee' 	: int(kw.get('employee')),
                'punch_time': kw.get('punch_time'),
                'punch_state':kw.get('punch_state'),
            }

            res = requests.post(f"{BASE_URL}{API}", auth=AUTH, json=params, timeout=15)
            if res.status_code not in  (200,201):
                return {'status': 'error', 'message': f"Failed to fetch punches:{res.status_code}\n {res.text}"}
            else:
                res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params={"ordering":"-id", "employee": int(kw.get('employee')),"page_size":1}, timeout=60)
                data = res.json()
                res.raise_for_status()
                if res.status_code not in  (200,201) :
                    return {'status': 'error', 'message': f"Failed to fetch punches:{res.status_code}\n {res.text}"}
            
                created = data.get("data", [])
                for tx in  created:
                    appr = requests.post(f"{BASE_URL}{API}/{tx.get('id')}/approve/", auth=AUTH, json={}, timeout=60)

                    values =[]
                    emp = request.env['hr.employee'].search([('zk_id','=',int(kw.get('employee')))],limit=1)
                    emp_code ,emp_id = emp.barcode,emp.zk_id
                    
                    pass
                    #return  {'status':'info', 'message':f'{appr.status_code}'}
                    if appr.status_code == 200:
                        # tparams = {"emp_code":emp_code,
                        #            "ordering":"-id",
                        #            "page_size":1,
                        #            'punch_time':kw.get('punch_time')
                        #            }
                        # 
                        # tres = requests.get(f"{BASE_URL}iclock/api/transactions/", auth=AUTH, params=tparams, timeout=60)
                        # if res.status_code != 200:
                        #     raise ValueError(f"Failed to fetch Transactions: {tres.text}")
                        # data = tres.json()
                        # tx_list = data.get("data", [])
                        # if not tx_list:
                        #     pass

                    
                        val = {
                            "tid"               :tx.get("id"),                
                            "emp"               :emp_id,                
                            "emp_code"          :emp_code,           
                            # "first_name"        :tx.get("first_name"),         
                            # "last_name"         :tx.get("last_name"),          
                            "punch_time"        :tx.get("punch_time"),         
                            "terminal_sn"       :"manual",        
                            "terminal_alias"    :"Manual",     
                            # "upload_time"       :tx.get("upload_time"),        
                        }


                            
                        _logger.info("👌 Approved")
                                
                        request.env['zk.transaction'].create(val)
                        request.env.cr.commit()

            #request.env['zk.terminals'].sync_manual_transaction("2025-11-01")
            return {f'status': 'success', 'message': f' attendance records added successfuly !'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    @http.route(['/my/attendance/delete/<int:emp_id>'], type='json', auth='user', website=True, methods=['POST'])
    def portal_delete_punch(self, emp_id, **kw):
        try:
            # Example: perform an action, e.g., mark attendance or send emails
            # Here we just simulate a process
            
            transaction = request.env['zk.transaction'].browse(int(emp_id))
            transaction.to_delete = True
            return {'status': 'success', 'message': f' attendance records marked for delete successfuly!{transaction.to_delete}'}

            BASE_URL        = request.env['ir.config_parameter'].sudo().get_param('zk.server')
            USER            = request.env['ir.config_parameter'].sudo().get_param('zk.user')
            PASSWORD        = request.env['ir.config_parameter'].sudo().get_param('zk.password')
            AUTH            = (USER, PASSWORD)

            API = f"iclock/api/transactions/{emp_id}/"

            
            res = requests.delete(f"{BASE_URL}{API}", auth=AUTH, params={}, timeout=60)
            
            if res.status_code != 200:
                return {'status': 'error', 'message': f"Failed to fetch punches: {res.text}"}
            return {'status': 'success', 'message': f' attendance records deleted successfuly!'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    

    @http.route(['/my/attendance/<string:start_day>','/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance_day(self, start_day=None, end_day=None, employee_type=None, **kw):
        employees = request.env['hr.employee'].search([])
        terminals = request.env['zk.terminals'].search([])
        
        if not start_day:
            start_day = request.env['zk.transaction'].search([],limit=1,order='punch_time desc').punch_time.date()
            return request.redirect(f'/my/attendance?start_day={start_day}')


        return request.render('nabi_hr.portal_attendance_template',{'employees':employees,'terminals':terminals,'start_day': start_day})

    # @http.route(['/my/attendance/json/<string:start_day>','/my/attendance/json'], type='json', auth='user',methods=['POST'], website=True,csrf=False)
    # def portal_attendance_json(self, start_day=None, end_day=None, employee_type=None,page=1, page_size=10 ,**kw):
     

    #     # Default month = current month
    #     if start_day:
    #         start_day = fields.Date.from_string(start_day) 
    #     else :
    #         start_day = datetime.today().date()
        
    #     if end_day:
    #         end_day = fields.Date.from_string(end_day) 
    #     else:
    #         end_day = start_day 
        

    #     # if employee_type:
    #     #     domain.append(('employee_type', '=', employee_type))

    #     domain = [('punch_time','>=',start_day),('punch_time','<=',end_day),('emp_code','!=',False)]
    #     # employees = request.env['hr.employee'].sudo().search(domain)

    #     portal_data = {}
    #     offset=(page-1) * page_size
    #     limit=page_size
    #     punches         = request.env['zk.transaction'].search(domain,).sorted(key=lambda x:((x.employee_id.barcode or '').zfill(6)))[offset:limit+offset]
        
    #     #,["id","tid", "punch_time", "terminal_alias", "emp_code","emp"])
    #     # punches = [
    #     #     {k: d[k] for k in ("id", "punch_time", "terminal_alias", "emp_code","emp_id")}
    #     #     for d in punches
    #     # ]

    #     main_punches    = punches.filtered(lambda x:x.usage == 't').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])#[p for p in punches if p['terminal_alias'] in MAIN_TYPE]
    #     entrance        = punches.filtered(lambda x:x.usage == 'p').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])# [p for p in punches if p['terminal_alias'] in ENTRANCE_TYPE]
    #     restaurant      =  punches.filtered(lambda x:x.usage == 'r').read(["id","tid", "punch_time", "terminal_alias", "emp_code","emp","sens"])# [p for p in punches if p['terminal_alias']=='restaurant']
        

    #     for punch in punches:  #sorted({p['punch_time'][:10] for p in punches}):
    #         day         = fields.Date.from_string(punch['punch_time']).strftime('%Y-%d-%m')
    #         employee_id = request.env["hr.employee"].search([('barcode','=',punch['emp_code'])],limit=1)
    #         key         = employee_id.id
 


    #         portal_data.setdefault(day,{})
    #         portal_data[day].setdefault(key ,{})
    #         portal_data[day][key].setdefault('emp_id',punch['emp'])
    #         portal_data[day][key].setdefault('employee_id',employee_id and employee_id.read(['barcode','name'])[0])



    #         portal_data[day][key].setdefault('punches',[])
    #         day_punches = [p for p in main_punches if  p['tid'] == punch['tid'] ]

    #         portal_data[day][key].setdefault('entrance_punches',[])
    #         day_entrance = [p for p in entrance if p['tid'] == punch['tid']]
            

    #         portal_data[day][key].setdefault('restaurant',[])
    #         day_restaurant = [p for p in restaurant if p['tid'] == punch['tid']][:1]

    #         portal_data[day][key].setdefault('exceptions',[])
            
            
    #         portal_data[day][key]['punches']             += day_punches
    #         portal_data[day][key]['entrance_punches']    += day_entrance
    #         portal_data[day][key]['restaurant']          += day_restaurant
            
            

    #         portal_data[day][key]['buttons'] = {'delete' : True,
    #                                        'add_punch':True,
    #                                        'add_leave': True,
    #                                        'change_schedule':True
                
    #         }

    #     new_portal_data = portal_data.copy() or {}
    #     for pkey,pval in portal_data.items():
    #         pvals = pval.copy()
    #         for key,data in pvals.items():
    #             # key         = pdata[0]
    #             # data        = pdata[1]
    #             day_punches     = portal_data[pkey][key]['punches']            
    #             day_entrance    = portal_data[pkey][key]['entrance_punches']   
    #             day_restaurant  = portal_data[pkey][key]['restaurant'][:1] 
    #             new_portal_data[pkey][key]['restaurant'] = day_restaurant

    #             print (f"####### {day_punches}")        
                
    #             exceptions , day_punches     = self._detect_exceptions(day_punches[:])#, punch['emp_code'])

    #             new_portal_data[pkey][key]['exceptions'] = exceptions
    #             new_portal_data[pkey][key]['punches'] = day_punches
                
    #             if day_entrance:
    #                 exceptions , day_entrance     = self._detect_exceptions(day_entrance[:])#, punch['emp_code'])
    #                 new_portal_data[pkey][key]['exceptions'] += exceptions
    #                 new_portal_data[pkey][key]['entrance_punches'] = day_entrance


    #             if not new_portal_data[pkey][key]['exceptions']:
    #                 new_portal_data[pkey].pop(key)

        
    #     portal_data = new_portal_data


    #     # Previous and next month for navigation
    #     prev_month = (start_day - timedelta(days=1)).strftime("%Y-%m-%d")
    #     next_month = (end_day + timedelta(days=1)).strftime("%Y-%m-%d")
    #     # 🔹 sort by day (ascending)
    #     # sorted_data = sorted(   
    #     #     portal_data.items(),
    #     #     key=lambda item: item[1]['day']
    #     # )

    #     return  {
    #         'portal_data'   : [list(v.values()) for k,v in portal_data.items()],
    #         'current_month' : start_day,
    #         'prev_month'    : prev_month,
    #         'next_month'    : next_month,
    #     }
    
    @http.route( ['/my/attendance/json/<string:start_day>', '/my/attendance/json'],  type='json', auth='user', methods=['POST'], website=True, csrf=False)
    def portal_attendance_json(self, start_day=None, end_day=None, page=1, page_size=10,filters={}, **kw):
        """
        JSON route used by portal attendance widget.
        Supports filtering by date range, search text, terminal, and type inclusion.
        """
        user        = request.env.user
        Employee    = request.env['hr.employee']
        Transaction = request.env['zk.transaction']

        # --------------------------
        # 1️⃣ Parse incoming params
        # --------------------------
        if not filters : 
            filters = kw.get('filters') or {}
        # employee_filter = (filters.get('employee') or '').strip().lower()
        terminal_filter = filters.get('terminal') and list(map(int,filters.get('terminal')) or [])
        _logger.info(f"✅ Terminals {filters.get('terminal')}")
        _logger.info(f"✅ Filters {filters}")

        include_doors = filters.get('include_doors', False)
        include_restaurant = filters.get('include_restaurant', False)
        date_from = filters.get('from')
        date_to = filters.get('to')

        # --------------------------
        # 2️⃣ Date range setup
        # --------------------------
        if start_day:
            start_day = fields.Date.from_string(start_day)
        elif date_from:
            start_day = fields.Date.from_string(date_from)
        else:
            start_day = fields.Date.today()

        if end_day:
            end_day = fields.Date.from_string(end_day)
        elif date_to:
            end_day = fields.Date.from_string(date_to)
        else:
            end_day = start_day


        # # Optional: Search by employee
        # if employee_filter:
        #     punches = punches.filtered(lambda x: employee_filter in (x.emp or '').lower() or employee_filter in (x.emp_code or '').lower())


        # --------------------------
        # 3️⃣ Domain setup
        # --------------------------
        domain = [
            ('punch_time', '>=', start_day),
            ('punch_time', '<', end_day + timedelta(days=1)),  # overnight
            ('emp_code', '!=', False),
            '!','|',('emp_code','=like','9999%'),('emp_code','=','1')

        ]

        # filter by terminal
        if terminal_filter:
            domain.insert(0,('terminal_id', 'in', terminal_filter))

        # type inclusion (usage field)
        usage_excluded = []
        if not include_doors:
            usage_excluded.append('p')
        if not include_restaurant:
            usage_excluded.append('r')
        if usage_excluded:
            domain.insert(0,('usage', 'not in', usage_excluded))

        _logger.info(f"✅ Filters ##### {domain}")

        # --------------------------
        # 4️⃣ Query & Pagination
        # --------------------------
        offset = (page - 1) * page_size
        punches = Transaction.sudo().search(domain, order="punch_time asc")[offset:offset + page_size]

        
        # --------------------------
        # 5️⃣ Categorize by type
        # --------------------------
        main_punches    = punches.filtered(lambda x: x.usage == 't').read(["id", "tid", "punch_time", "terminal_alias", "emp_code", "emp", "sens"])
        entrance        = punches.filtered(lambda x: x.usage == 'p').read(["id", "tid", "punch_time", "terminal_alias", "emp_code", "emp", "sens"])
        restaurant      = punches.filtered(lambda x: x.usage == 'r').read(["id", "tid", "punch_time", "terminal_alias", "emp_code", "emp", "sens"])

        portal_data = {}

        # --------------------------
        # 6️⃣ Organize by day & employee
        # --------------------------
        for punch in punches:
            day = fields.Date.to_string(fields.Date.from_string(str(punch.punch_time)) )#or start_day)
            emp_rec = Employee.sudo().search([('barcode', '=', punch.emp_code)], limit=1)
            emp_key = emp_rec.id

            portal_data.setdefault(day, {})
            emp_data = portal_data[day].setdefault(emp_key, {
                'day':day,
                'emp_id': punch.emp,
                'employee_id': emp_rec and emp_rec.read(['barcode', 'name'])[0],
                'punches': [],
                'entrance_punches': [],
                'restaurant': [],
                'exceptions': [],
                'buttons': {
                    'delete': True,
                    'add_punch': True,
                    'add_leave': True,
                    'change_schedule': True,
                }
            })

            emp_data['punches'] += [p for p in main_punches if p['tid'] == punch.tid]
            emp_data['entrance_punches'] += [p for p in entrance if p['tid'] == punch.tid]
            emp_data['restaurant'] += [p for p in restaurant if p['tid'] == punch.tid][:1]

        # --------------------------
        # 7️⃣ Detect anomalies
        # --------------------------
        new_portal_data = {}
        for day, employees in portal_data.items():
            new_portal_data[day] = {}
            for emp_key, data in employees.items():
                day_punches = data['punches']
                exceptions, cleaned = self._detect_exceptions(day_punches[:])
                data['exceptions'] = exceptions
                data['punches'] = cleaned

                if data['entrance_punches']:

                    ex2, cleaned2 = self._detect_exceptions(data['entrance_punches'][:],INTERVAL=5)
                    data['exceptions'] += ex2
                    data['entrance_punches'] = cleaned2
                    #_logger.info(f"✅ anomalie entrance  {len(data['entrance_punches'])} / {len(cleaned2)}")

                if data['exceptions']:
                    new_portal_data[day][emp_key] = data

        # --------------------------
        # 8️⃣ Prev / Next Day
        # --------------------------
        prev_day = (start_day - timedelta(days=1)).strftime("%Y-%m-%d")
        next_day = (start_day + timedelta(days=1)).strftime("%Y-%m-%d")

        # --------------------------
        # 9️⃣ Return data
        # --------------------------
        return {
            'portal_data': [list(v.values()) for v in new_portal_data.values()],
            'current_day': start_day.strftime("%Y-%m-%d"),
            'prev_day': prev_day,
            'next_day': next_day,
            'filters' : filters,
        }
    
    def _fetch_punches(self, emp=None, day_from=None, day_to=None):
        # Call Zkbiotime API for this employee and day range
        # Return list of dicts with keys: punch_time, device_type, terminal_sn, terminal_alias
        return request.env['zk.connector'].sudo().get_punches(emp_code=emp and emp.barcode or None, day_from=day_from, day_to=day_to)

    def _detect_exceptions(self,punches, emp=None,INTERVAL=None):
        exceptions = []
        if emp  and   not isinstance(emp, type(request.env['hr.employee'])) :
            emp = request.env['hr.employee'].search([('active','in',(True,False)),('barcode','=',emp)])
            

        # duplicate detection (same device within 5 min)
        seen = {}
        _logger.info(f"❌ punch lenght → {len(punches)}")
        sorted_punches = sorted(punches[:] ,key=lambda x:x["punch_time"]) 
        for o in sorted_punches:
            if o['sens'] == 'out':
                sorted_punches.remove(o)
            else:
                break

        for p in sorted_punches:
            
            emp_code    = p["emp_code"]
            tid         = p["id"]
            terminal    = p["terminal_alias"]
            punch_time  = p["punch_time"]
            # punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")
            punch_day = punch_time.date()

            key = ( terminal, punch_day)
            if emp_code == "6107":_logger.info(f"❌ key  → {terminal} | {punch_time}")
            
            if key in seen:
                delta = (punch_time - seen[key])
                seen[key] = punch_time
                if emp_code == "6107":_logger.info(f"❌ Delta → {delta} ")
                if delta <= timedelta(minutes=INTERVAL or DUPLUCATE_INTERVAL or 5):
                    if emp_code == "6107":_logger.info(f"❌ Duplicate → {terminal} | {punch_time}")
                    #p.duplicate = True
                    sorted_punches.remove(p)
                    #delete_transaction(tid)
            #     else:
            #         seen[key] = punch_time
            else:
                if emp_code == "6107":_logger.info(f"✔️ Keeping punch → ID {tid} | Emp {emp_code} | {punch_time}")
                seen[key] = punch_time

        # missing main punches
        #main_punches = [p for p in punches if terminal in MAIN_TYPE ]
        if len(sorted_punches) < 2:
            exceptions.append(f'pointage raté !')

        # # missing restaurant for 6-14 usine
        # if emp and emp.employee_type=='worker':  # and emp.shift=='6-14'
        #     if not any(terminal=='restaurant' for p in punches):
        #         exceptions.append('missing_restaurant')

        return list(set(exceptions)),sorted_punches


    @http.route(['/my/attendance/get_anomalie','/my/attendance/get_anomalie/<string:emp_id>'], type='http', auth='user', website=True, methods=['POST','GET'],csrf=False)
    def portal_get_anomalie(self, start_day: date = None, end_day: date = None, emp_id : int = 0,terminal_ids :list =[],**kw):
        
        employees = request.env['hr.employee'].search([('active','in',(True,False)),])
        terminals = request.env['zk.terminals'].search([])
        
        if not start_day:
            start_day = request.env['zk.transaction'].search([],limit=1,order='punch_time desc').punch_time.date()
            return request.redirect(f'/my/attendance/get_anomalie?start_day={start_day}')
        else:
            start_day = fields.Date.from_string(start_day)

        if end_day:
            end_day = fields.Date.from_string(end_day)


        

        domain = [('punch_time','>=',start_day)] 
        if end_day:
            domain+= [('punch_time','<=',end_day)] 
        else:
            domain+= [('punch_time','<',start_day+timedelta(days=1))] 
            
        domain += ['!','|',('emp_code','=like','9999%'),('emp_code','=','1')]
        punches = request.env['zk.transaction'].search(domain).grouped(lambda x:x.punch_time.date())
        portal_punches = {}

        for d, p in punches.items():
            pday = dict([ (e,p.browse()) for e in  request.env['hr.employee'].search([('barcode','=like','__%'), '!','|',('barcode','=like','9999%'),('barcode','=','1')]) - p.mapped('employee_id')])
            pday.update( p.grouped(lambda x:x.employee_id))

            portal_punches[d] = pday



        return request.render('nabi_hr.portal_attendance_anomalie_template',{
                'portal_punches'    : portal_punches,
                'employees'         : employees,
                'terminals'         : terminals,
                'emp_id'            : emp_id,
                'start_day'         : start_day,
                'end_day'           : end_day,
                "kw"                : kw,
                "domain"            : domain
                })