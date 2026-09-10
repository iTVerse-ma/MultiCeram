# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

from datetime import date, timedelta
import requests


def is_host_reachable(host, AUTH, timeout=3):
    try:
        with requests.get(f"{host}/att/api/", auth=AUTH, params={}, timeout=timeout):
            return True
    except Exception as e:
        return False

class ResteDayPortal(http.Controller):

    @http.route('/my/reste-days', type='http', auth='user', website=True)
    def portal_reste_days(self, **kw):
        today           = date.today()
        current_week    = today.isocalendar()[1]
        employee        = request.env['hr.employee'].search([('user_id','=',request.env.user.id)]) 
        emp_id          = employee and employee.zk_id and int(employee.zk_id) or 592        
        
        BASE_URL,_,_,AUTH   = request.env["zk.connector"]._get_connection_params()
        schAPI              = "/att/api/attschedules/"
        shiftAPI            = "/att/api/attshifts/"
        shiftDetailAPI      = "/att/api/shift_details/"
        IntervalAPI         = "/att/api/timeintervals/"
        err                 = []
        WE = None
        
        if not is_host_reachable(BASE_URL, AUTH):
            err.append("Cannot connect to biotime server — skipping API call", )
            return request.render("nabi_hr.portal_reste_days", {"weeks": [],
                            "message": kw.get("message"),
                            "errors" : err})
                            
        else:
            try:
                response = requests.get(f"{BASE_URL}{IntervalAPI}", auth=AUTH, params={"alias":"WE"}, timeout=60)
                if response.status_code == 200:
                    WE = response.json().get('data')[0].get('id')
                else:
                    WE = None
            except requests.exceptions.RequestException as e:
                err.append("Erreur connexion API timeintervals: %s", e)
                WE = None

        existing_days = {}
        if emp_id:
            schParams = {
                    "employee": emp_id,
                    "page_size":10000
                }
            
            shift_res       = requests.get(f"{BASE_URL}{schAPI}", auth=AUTH, params=schParams, timeout=60)
            shift_data      = shift_res.json()
            shifts          = shift_data.get("data")
            
            # err.append(f"get existing schedules : "  )
            # err.append(f".  payload= {schParams}  - response = {shift_res.text} ")
            # err.append(f".  Response = {shift_res.text} ")

            day_index = None
            
            for shift in shifts:
                sdparams            = {"page_size":10000,"shift":shift.get("shift")}
                shiftdetailResp     = requests.get(f"{BASE_URL}{shiftDetailAPI}",auth=AUTH, params=sdparams,timeout=60)
                shiftdet_data       = shiftdetailResp.json()
                shiftsDet           = shiftdet_data.get("data")
                for d in shiftsDet:
                    if d.get("time_interval") == WE:
                        # err.append(f"shiftsDet = {d} --> {WE}")
                        day_index = d.get("day_index")
                if not day_index:
                    continue




                start_date      = date.fromisoformat(shift.get("start_date")) + timedelta(days=day_index-1)
                wk              = start_date.isocalendar()[1]
                existing_days.setdefault(wk,[])
                existing_days[wk].append( start_date.strftime('%Y-%m-%d'))
                
                
                
                # err.append(f" existing_days : {existing_days}")
        else:
            pass
            err.append("Employee not exists ! ")

        weeks = []
        for offset in range(-2, 9):  # n-2 → n+8
            monday = today + timedelta(weeks=offset, days=-today.weekday())
            sunday = monday + timedelta(days=6)
            wk_num = monday.isocalendar()[1]

            days = []
            for i in range(7):
                d = monday + timedelta(days=i)
                iso = d.strftime("%Y-%m-%d")
                days.append({
                    "date": iso,
                    "label": d.strftime("%d"),  # juste le jour du mois
                    "day_of_week": d.strftime("%a"),  # Mon, Tue, etc.

                    "selected": existing_days.get(wk_num) and iso in existing_days.get(wk_num),

                    "is_today": (d == today),
                    "shift" : f"WE_{d.strftime("%a").upper()}_3S"
                })
            weeks.append({
                "week_num": wk_num,
                "start": monday,
                "end": sunday,
                "days": days,
                "is_current": (wk_num == current_week),
            })

        return request.render("nabi_hr.portal_reste_days", {
            "weeks": weeks,
            "message": kw.get("message"),
            "errors" : err
        })

    @http.route('/my/toggle-reste-day', type='http', auth='user', methods=["POST"], website=True, csrf=False)
    def toggle_reste_day(self,  **post):
        
        employee    = request.env['hr.employee'].search([('user_id','=',request.env.user.id)]) 
        emp_id      = employee and employee.zk_id and int(employee.zk_id) or 592
        date_str        = post.get("reste_date")
        selected_shift  = post.get("shift")
        d               = date.fromisoformat(date_str)
        wk              = d.isocalendar()[1]
        reste_type      = request.env['hr.leave.type'].sudo().search([('name', '=', 'Reste Day')], limit=1)
        deb             = selected_shift
        err             =   []
        msg = []
        shiftAPI = "/att/api/attshifts/"
        BASE_URL,_,_,AUTH = request.env["zk.connector"]._get_connection_params()

        if not emp_id :
            return request.redirect("/my/reste-days?message=Employee mal configurée")

        # existing = request.env['hr.leave'].sudo().search([
        #     ('employee_id', '=', employee.id),
        #     ('holiday_status_id', '=', reste_type.id),
        #     ('request_date_from', '>=', d - timedelta(days=d.weekday())),  # semaine courante
        #     ('request_date_to', '<=', d + timedelta(days=(6 - d.weekday()))),
        # ])
        

        # params = {
        #         "start_date"        : (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d'),
        #         "end_date"          : (d + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'),
        #         "employee"          : emp_id,
        #         "shift"             : selected_shift
        #     }
        shift_params = {
            "alias": selected_shift,
            "page_size":1
        }
        
        shift_res       = requests.get(f"{BASE_URL}{shiftAPI}", auth=AUTH, params=shift_params, timeout=60)
        shift_data      = shift_res.json()
        shift_ids       = shift_data.get("data")
        # msg=f"{shift_data}"
        # return request.redirect(f"/my/reste-days?error={msg}")
        if shift_ids:

            shift_id =  shift_ids[0].get("id")
        else:
            return request.redirect(f"/my/reste-days?message=shift mal configuré")
            
            
                
        BASE_URL,_,_,AUTH = request.env["zk.connector"]._get_connection_params()

        API = f"/att/api/attschedules/"
        params = {
                "start_date": (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d'),
                "end_date": (d + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'),
                "employee": emp_id,
                "shift": shift_id,
                "page_size":10,
                "page":99999999999999

            }
        res = requests.get(f"{BASE_URL}{API}", auth=AUTH, params=params, timeout=60)

        if res.status_code != 200:
            return  request.redirect(f"/my/reste-days?message= message 2 {params}{res.text}")
        data = res.json()
        existing = data.get("data", [])
        # err.append(f"Existing {existing}:")
        # err.append(f"payload =  {params}")
       


        if existing :
            # toggle OFF (désélection)
            # existing.filtered(lambda x:x.request_date_from == d).unlink()
            for shift in existing:
                if shift.get("start_date") >= (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d') and shift.get("end_date") <= (d + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'):
                    requests.delete(f"{BASE_URL}{API}/{shift['id']}/", auth=AUTH, params={}, timeout=60)
                    # err.append( f"shift to delete {shift} ")
        if True:
            # supprimer autre jour de la semaine si existe
            # if existing:
            #     existing.unlink()

            # ajouter le jour sélectionné
            # request.env['hr.leave'].sudo().create({
            #     "name": "Reste Day",
            #     "employee_id": employee.id,
            #     "holiday_status_id": reste_type.id,
            #     "request_date_from": date_str,
            #     "request_date_to": date_str,
            # })
            schAPI = f"/att/api/attschedules/"
            sch_params = {
                    "start_date": (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d'),
                    "end_date": (d + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'),
                    "employee": emp_id,
                    "shift": shift_id
                }
            res = requests.post(f"{BASE_URL}{schAPI}", auth=AUTH, json=sch_params, timeout=60)
            deb = f"else = {sch_params}{res.text}"

            
            # propagation aux semaines futures si pas déjà défini
            for i in range(1, 9):
                future = d + timedelta(weeks=i)
                # wk_future = future.isocalendar()[1]

                # already = request.env['hr.leave'].sudo().search([
                #     ('employee_id', '=', employee.id),
                #     ('holiday_status_id', '=', reste_type.id),
                #     ('request_date_from', '>=', future - timedelta(days=future.weekday())),
                # ])
                schAPI = f"/att/api/attschedules/"
                sch_params = {
                        "start_date": (future - timedelta(days=d.weekday())).strftime('%Y-%m-%d'),
                        "end_date": (future + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'),
                        "employee":emp_id,
                        "shift": shift_id,
                        "page_size":1
                    }
                already = requests.get(f"{BASE_URL}{schAPI}", auth=AUTH, params=sch_params, timeout=60)



                if not already:
                    # request.env['hr.leave'].sudo().create({
                    #     "name": "Reste Day",
                    #     "employee_id": employee.id,
                    #     "holiday_status_id": reste_type.id,
                    #     "request_date_from": future,
                    #     "request_date_to": future,
                    # })
                    schAPI = f"/att/api/attschedules/"
                    sch_params = {
                            "start_date": (future - timedelta(days=d.weekday())).strftime('%Y-%m-%d'),
                            "end_date": (future + timedelta(days=(6 - d.weekday()))).strftime('%Y-%m-%d'),
                            "employee": emp_id,
                            "shift": shift_id
                        }
                    res = requests.post(f"{BASE_URL}{schAPI}", auth=AUTH, params=sch_params, timeout=60)

            msg = f"Jour de repos {date_str} sélectionné "

        return request.redirect(f"/my/reste-days?errors={err}&message={msg}- {deb}")