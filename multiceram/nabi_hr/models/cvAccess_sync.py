# -*- coding: utf-8 -*-

from odoo import models,fields, api, _
import requests,json,base64
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)
from typing import Optional





class CVSecuritysSync(models.Model):
    _name = 'zk.cvsecurity.sync'
    _description = 'Sync CVSecurity Transactions to BioTime'

    @api.model
    def cron_sync_cvsecurity(self, startDate:Optional[datetime]=None, endDate:Optional[datetime]=None):
        """Fetch cvsecurity logs and create manual entries in BioTime"""
        
        biotime_url, _, _, AUTH = self.env["zk.connector"]._get_connection_params()
        
        cvsecurity_url        = self.env['ir.config_parameter'].sudo().get_param('zk.cvsecurity_url')
        cvsecurity_token   = self.env['ir.config_parameter'].sudo().get_param('zk.cvsecurity_token')
        base_url = f"{biotime_url}att/api/manuallogs/"
        cdata = f"{biotime_url}iclock/cdata"
        serial_number = "TESTSN12345"

        
        if not (base_url and biotime_url):
            _logger.warning("⚠️ cvsecurity/BioTime not configured in system parameters")
            return
        
        if not startDate:
            startDate = datetime.now() + timedelta(days=-1)
        if not endDate:
            endDate = datetime.now()
        transactions = []
        try:
            page = 1
            while True:    
                url = f"{cvsecurity_url}api/v2/transaction/list?access_token={cvsecurity_token}&pageNo={page}&pageSize=1000&startDate={startDate}&endDate={endDate}"
                _logger.error(url)
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                response = r.json()
                transactions +=response['data']['data']
                page+=1
                if response['data']['lastPage']:
                    break
                
                
        except Exception as e:
            _logger.error(f"❌ Failed to fetch cvsecurity data: {e}")
            return

        # headers = {"Authorization": f"Token {biotime_token}"}
        recent_tx_cache = {}

        mvts = []
        for tx in transactions:
            pin         = tx.get("pin")
            reader_name = tx.get("readerName", "")
            event_time  = tx.get("eventTime")

            # Ignore empty pins
            if not pin:
                continue
            
            # Convert CVAccess time to datetime
            punch_dt    = datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S")
            key         = f"{pin}"

            # Check cache for duplicates within 5 min
            last_tx_time = recent_tx_cache.get(key)
            if last_tx_time and ( last_tx_time - punch_dt ) < timedelta(minutes=5):
                _logger.info(f"⏩ Ignored duplicate from CVAccess: {pin} on {reader_name} at {event_time}")
                continue
            recent_tx_cache[key] = punch_dt

            # Find employee by acc_pin / acc_pin2
            employee = self.env['hr.employee'].sudo().search([('active','in',(True,False)),
                '|', ('x_acc_pin', '=', pin), ('x_acc_pin2', '=', pin)
            ], limit=1)

            if not employee:
                _logger.info(f"🚫 No employee found for PIN {pin}")
                continue

            # Determine IN/OUT
            if "Hors" in reader_name:
                punch_state = 0  # OUT
            elif "En" in reader_name:
                punch_state = 1  # IN
            else:
                punch_state = 0

            # Convert time
            punch_dt = datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S")
            since_dt = punch_dt - timedelta(minutes=5)

            

            # Create manual entry in BioTime
            payload = {
                "employee": f"{employee.barcode}",
                "punch_time": f"{event_time}",
                "punch_state": f"{punch_state}",
                "apply_reason": f"Cv Access - {reader_name} "
            }
            mvts.append(payload)

           
            #work_code	
           
            
            
            
            
            # try:
            #     resp = requests.post(base_url, auth=AUTH, json=payload)
            #     if resp.status_code in (200, 201):
            #         _logger.info(f"{resp.text}")
            #         _logger.info(f"✅ Created log for {employee.name} at {event_time} {payload}")
            #         search_payload =  {
            #                 "employee": f"{employee.zk_id}",
            #                 "ordering": "-id",
            #                 "pageSize":1,
                            
            #             }
            #         created = requests.get(f"{base_url}?pageSize=1&ordering=-id&employee={employee.zk_id}", auth=AUTH, )
            #         created.raise_for_status()
            #         created_id = created.json()["data"][0].get('id',False)
            #         err=f"{base_url}{created_id}/approve/"
            #         _logger.error(err)
                    
            #         if created_id:
            #             approved = requests.post(f"{base_url}{created_id}/approve/", auth=AUTH, )
            #             approved.raise_for_status()
                        
                        
                    
            #     else:
            #         _logger.warning(f"⚠️ Failed to push log for {employee.name}: {resp.text}")
            # except Exception as e:
            #     _logger.error(f"Error creating log: {e}")
                
            #Approve 
        body = "\n".join([f"{t['employee']}\t{t['punch_time']}\t{t['punch_state']}\t0" for t in mvts])
        _logger.warning(body)
        # Send as if from device
        resp = requests.post(
            f"{cdata}?SN={serial_number}&table=ATTLOG",
            headers={"Content-Type": "text/plain"},
            data=body.encode('utf-8')
        )

        _logger.warning(f"⚠️ Status:{resp.status_code}")
        _logger.warning(f"⚠️ Response:{resp.text}")
            
            
            
            
            
            