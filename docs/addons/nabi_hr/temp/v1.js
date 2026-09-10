/* @odoo-module */
//
// This file is meant to regroup your javascript code. You can either copy/past
// any code that should be executed on each page loading or write your own
// taking advantage of the Odoo framework to create new behaviors or modify
// existing ones. For example, doing this will greet any visitor with a 'Hello,
// world !' message in a popup:
//
/*
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import publicWidget from '@web/legacy/js/public/public_widget';

publicWidget.registry.HelloWorldPopup = publicWidget.Widget.extend({
    selector: '#wrapwrap',

    init() {
        this._super(...arguments);
        this.dialog = this.bindService("dialog");
    },
    start() {
        this.dialog.add(ConfirmationDialog, { body: 'Hello World' });
        return this._super.apply(this, arguments);
    },
});
*//* @odoo-module */
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import { Dialog }             from '@web/core/dialog/dialog';
import publicWidget           from '@web/legacy/js/public/public_widget';
import { rpc }                from '@web/core/network/rpc';
import { Component, xml, useState } from "@odoo/owl";
import {renderToElement}      from "@web/core/utils/render";
const { markup} = require("@odoo/owl");
//#################

let currentPage = 1;
const pageSize = 100;
const match = window.location.pathname.match(/\/my\/attendance\/(\d{4}-\d{2}-\d{2})/);
let dateStr = null;

if (match) {
     dateStr = match[1]; // "2025-09-22"
    console.log("Found date:", dateStr);
}


async function loadPage(page = 1, append = false) {
    const result = await rpc(`/my/attendance/json/${dateStr}`, { page, page_size: pageSize });
    const list = document.getElementById("attendance-list");

    if (!append) list.innerHTML = "";
    console.log("portal_data",result.portal_data);
    
    if (result.portal_data.length>0 && result.portal_data[0].length>0){
    result.portal_data[0].forEach(async record => {
      
        const row = document.createElement("tr");
        row.classList.add("attendance-row");
        console.log(record.punches);
        const a = xml`<tr>
            <td>${record.employee_id.barcode.padStart(6, "0")}</td>
            <td>${record.employee_id.name}</td>
           
            <td class="punches">
                ${(record.punches || []).map(
                    punch => `<span class="card badge bg-success ms-1">${(!punch.terminal_alias?'M ':'')} ${punch.punch_time.split(" ")[1]}
                                    <i  class="fa fa-times text-danger"  
                                            data-action="delete"  
                                            data-id="${punch.id}"/>
                                    </span>`
                ).join("")}
            </td>
            <td class="entrance_punches">
                ${(record.entrance_punches || []).map(
                    punch => `<span class="badge bg-success ms-1">${punch.punch_time.split(" ")[1]}</span>`
                ).join("")}
            </td>
            <td class="restaurant">
                ${(record.restaurant || []).map(
                    punch => `<span class="badge bg-success ms-1">${punch.punch_time.split(" ")[1]}</span>`
                ).join("")}
            </td>
            <td class="exceptions">
                ${(record.exceptions || []).map(
                    punch => `<span class="badge bg-success ms-1">${punch}</span>`
                ).join("")}
            </td>
            <td>
               
                <button class="btn btn-sm btn-success"
                        data-action="add_punch" 
                        data-id="${record.id}" 
                        data-empid="${record.emp_id}" 
                        data-curdate="${dateStr}">
                    <i class="fa fa-plus"></i>
                </button>
                <button class="btn btn-sm btn-warning"
                        data-action="add_leave" 
                        data-empid="${record.emp_id}" 
                        data-curdate="${dateStr}">
                    <i class="fa fa-plane"></i>
                </button>
            </td></tr>
        `;

       list.append( renderToElement(a))
        
       
       // list.appendChild(row);
        
    });

    }else{
      
      currentPage = page;
    }
      
    }

document.addEventListener("click", async (e) => {
    if (e.target.matches("[data-action=delete]")) {
        const id = e.target.dataset.id;
        const action = e.target.dataset.action;
        await rpc(`/my/attendance/delete/${id}`, { action });
        e.target.closest(".card").remove(); // disappear instantly
    }
    if (e.target.matches("[data-action=add_punch]")) {
        const id = e.target.dataset.id;
        const action = e.target.dataset.action;
        await rpc(`/my/attendance/add_punch/`, { action });
        e.target.closest(".card").remove(); // disappear instantly
    }
    if (e.target.matches("[data-action=delete]")) {
        const id = e.target.dataset.id;
        const action = e.target.dataset.action;
        await rpc(`/my/attendance/add_leave/`, { action });
        e.target.closest(".card").remove(); // disappear instantly
    }
});

document.getElementById("load-more").addEventListener("click", () => {
    currentPage++;
    loadPage(currentPage, true);
});

// Auto refresh every 10s for new records
setInterval(() => {loadPage(currentPage, true);currentPage++}, 10000);

loadPage();



//################
publicWidget.registry.RunActionWidget =  publicWidget.Widget.extend({
    selector: 'span[data-action],button[data-action],i[data-action]',

    init() {
        this._super(...arguments);
        this.dialog = this.bindService("dialog");
        this.rpc = rpc;
    },

    start: function () {
        var self = this;

        self.$el.filter('[data-action="delete"]').on('click', function () {
          //console.log(self.el.dataset.id)
            // Show confirmation dialog first
            self.dialog.add(ConfirmationDialog, {
                title: "Confirm",
                body:markup(`<b>Êtes vous sur de vouloir supprimer cette entrée ?</B>`),
                confirm: async function () {
                    // Call your controller route
                    await self.rpc(`/my/attendance/delete/${self.el.dataset.id}`,{ 'csrf_token': odoo.csrf_token,
                        
                        
                    }).then(function (result) {
                        // Show success/error in a modal
                        self.dialog.add(ConfirmationDialog, {
                            title: result.status === 'success' ? `Success ${self.el.dataset.id}` : "Error",
                            body: result.message,
                            confirm: function () {
                                // Optional: reload page or table here
                                console.log('Dialog closed');
                            }
                        });
                    });
                }
            });
       //tto
       
        });
        // Add manual punch
        self.$el.filter('[data-action="add_punch"]').on('click', function (ev) {
            const empId = this.dataset.empid;
            // Prefill values
            const now = new Date();
            const nowStr = this.dataset.curdate;

            const formHtml = `  <form id="manualPunchForm" class="p-2">
                                  <input type="hidden" name="employee" value="${empId}"/>
                          
                                  <div class="form-group row">
                                      <label class="fw-bold small">Punch Time</label>
                                      <input type="datetime-local" name="punch_time" 
                                             class="form-control form-control-sm" 
                                             required value="${nowStr}"/>
                                  
                                      <label class="fw-bold small">Punch State</label>
                                      <select name="punch_state" 
                                              class="form-select form-select-sm" required>
                                          <option value="1">Check-In</option>
                                          <option value="2">Check-Out</option>
                                      </select>
                                  
                                      <label class="fw-bold small">Reason</label>
                                      <input type="text" name="apply_reason" 
                                             class="form-control form-control-sm" 
                                             placeholder="Reason (optional)"/>
                                  </div>
                              </form>
                          `;

            self.dialog.add(ConfirmationDialog, {
                title: "Add Manual Punch",
                body: markup(formHtml),
                confirmLabel: "Save",
                confirm: async function () {
                    const form = document.getElementById("manualPunchForm");
                    const payload = {
                        employee: empId,
                        punch_time: form.punch_time.value,
                        punch_state: form.punch_state.value,
                        apply_reason: form.apply_reason.value || "",
                        work_code: "",
                    };

                    try {
                        let result = await rpc("/my/attendance/add_punch", payload);
                        self.dialog.add(ConfirmationDialog, {
                            title: result.status === 'success' ? "✅ Created" : "❌ Error",
                            body: result.message || "",
                            confirm: function () {
                                if (result.status === 'success') {
                                    // Ajouter la nouvelle punch dans le tableau
                                    const row = $(self.el).closest("tr");
                                    row.find("td.punches").append(
                                        `<span class="badge bg-success ms-1">${payload.punch_time.slice(11,16)}</span>`
                                    );
                                }
                            }
                        });
                    } catch (err) {
                        console.error(err);
                        self.dialog.add(ConfirmationDialog, {
                            title: "Error",
                            body: "Failed to add punch",
                        });
                    }
                }
            });
       
        });
        // Add leave 
        self.$el.filter('[data-action="add_leave"]').on('click', function (ev) {
            const empId = this.dataset.empid;
            // Prefill values
            const now = new Date();
            const nowStr = this.dataset.curdate;

            const formHtml = `  <form id="leaveForm" class="p-2">
                                  <input type="hidden" name="employee" value="${empId}"/>
                          
                                  <div class="form-group row">
                                      <label class="fw-bold small">Punch Time</label>
                                      <input type="datetime-local" name="start_time" 
                                             class="form-control form-control-sm" 
                                             required value="${nowStr}"/>
                                      <input type="datetime-local" name="end_time" 
                                             class="form-control form-control-sm" 
                                             required value="${nowStr}"/>
                                  
                                      <!-- <label class="fw-bold small">Punch State</label>
                                      <select name="punch_state" 
                                              class="form-select form-select-sm" required>
                                          <option value="1">Check-In</option>
                                          <option value="2">Check-Out</option>
                                      </select>
                                      -->
                                  
                                      <label class="fw-bold small">Reason</label>
                                      <input type="text" name="apply_reason" 
                                             class="form-control form-control-sm" 
                                             placeholder="Reason (optional)"/>
                                  </div>
                              </form> `;

            self.dialog.add(ConfirmationDialog, {
                title: "Add leave",
                body: markup(formHtml),
                confirmLabel: "Save",
                confirm: async function () {
                    const form = document.getElementById("leaveForm");
                    const payload = {
                        employee: empId,
                        start_time: form.punch_time.value,
                        end_time: form.punch_state.value,
                        //apply_reason: form.apply_reason.value || "",
                        pay_code: 12,
                        work_code: "",
                    };

                    try {
                        let result = await rpc("/my/leaves/add_leaves", payload);
                        self.dialog.add(ConfirmationDialog, {
                            title: result.status === 'success' ? "✅ Created" : "❌ Error",
                            body: result.message || "",
                            confirm: function () {
                                if (result.status === 'success') {
                                    // Ajouter la nouvelle punch dans le tableau
                                    const row = $(self.el).closest("tr");
                                    row.find("td.punches").append(
                                        `<span class="badge bg-success ms-1">${payload.punch_time.slice(11,16)}</span>`
                                    );
                                }
                            }
                        });
                    } catch (err) {
                        console.error(err);
                        self.dialog.add(ConfirmationDialog, {
                            title: "Error",
                            body: "Failed to add punch",
                        });
                    }
                }
            });
       
        });
    }
});