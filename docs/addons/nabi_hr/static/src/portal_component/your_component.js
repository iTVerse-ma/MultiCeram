

/* @odoo-module */
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';
import { xml } from "@odoo/owl";
import { renderToElement } from "@web/core/utils/render";
const { markup } = require("@odoo/owl");
// import { AttendancePortalLine } from "./attendanceLine";
// import { DateTimePicker } from "@web/core/datetime/datetime_picker";




// ##############################
// Global variables
// ##############################
let   currentPage   = 1;
const pageSize      = 5000;
const match         = window.location.pathname.match(/\/my\/attendance\/(\d{4}-\d{2}-\d{2})/);
let   dateStr       = match ? match[1] : null;

const prms = new URLSearchParams(window.location.search);
let   dateStart   = prms.get('start_day',null)
let   dateEnd   = prms.get('end_day',null)


// ##############################
// Attendance Widget
// ##############################

publicWidget.registry.AttendancePortal = publicWidget.Widget.extend({
    selector: "#attendance-portal",   // wrapper attendu dans ton template
    // components : {AttendancePortalLine},

    // seuls les clics sur actions restent dans events (les inputs sont attachés dans start)
    events: {
        "click #load-more"                  : "_onLoadMore",
        "click [data-action=delete]"        : "_onDelete",
        "click [data-action=add_punch]"     : "_onAddPunch",
        "click [data-action=add_leave]"     : "_onAddLeave",
        "click [data-action=get_punches]"   : "_onGetPunches",
        "click #prev-day"                   : "_onPrevDay",
        "click #next-day"                   : "_onNextDay",
        "click #filter_apply"              : "_onApplyFilters",
        "click [data-action=show_report]"   : "_onShowReport",
    },

    init() {
        //console.log("init",currentPage);
        //this._super(...arguments);
        this.dialog = this.bindService("dialog");
        this.rpc = rpc;
        this._refreshInterval = null;
        // this.initDatePickers();
        // this.bindEvents();
        // this.initOdooDatePickers();
    },
    // bindEvents: function () {
    //     const self = this;

    //     this.$el.find('#apply_filters').on('click', function () {
    //         self.applyFilters();
    //     });

    //     this.$el.find('#filter_from, #filter_to').on('change', function () {
    //         self.applyFilters();
    //     });
    // },
    // initOdooDatePickers: function () {
    //     const fromInput = this.el.querySelector('#filter_from');
    //     const toInput = this.el.querySelector('#filter_to');

    //     if (fromInput) {
    //         new DateTimePicker(null, fromInput, { mode: "date" });
    //     }
    //     if (toInput) {
    //         new DateTimePicker(null, toInput, { mode: "date" });
    //     }
    // },

    

    async start() {
        //console.log("start",currentPage);
        // listeners pour recherche / filtre (attachés sur le container pour garantir qu'ils existent)
        const searchInput  = this.el.querySelector("#attendance_search");
        const filterSelect = this.el.querySelector("#attendance_filter");
        if (searchInput)   searchInput.addEventListener("input", this._applyFilter.bind(this));
        if (filterSelect) filterSelect.addEventListener("change", this._applyFilter.bind(this));
        
        


        // // load initial
        // await this._loadPage(1, false);
        // currentPage++;
        // // Auto refresh every 10s (on stocke l'id pour pouvoir clearInterval dans destroy)
        // this._refreshInterval = setInterval(async () => {
        //     await this._loadPage(currentPage, true);
        //     currentPage++;
        // }, 10000);

        return Promise.resolve() //this._super(...arguments);
    },

    destroy() {
      console.log("destrow",currentPage);
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
        return Promise.resolve() 
        //return this._super(...arguments);
    },

    // ------------------------------
    // Helpers
    // ------------------------------
    async _onApplyFilters() {
    const params = {
        // search: this.el.querySelector("#attendance_search")?.value || "",
        // employee: this.el.querySelector("#filter_employee")?.value || false,
        // terminal: this.el.querySelector("#filter_terminal")?.value || "",
        terminal: Array.from(this.el.querySelector("#filter_terminal")?.selectedOptions).map(opt=>opt.value) || false,


        from: this.el.querySelector("#filter_from")?.value || false,
        to: this.el.querySelector("#filter_to")?.value || false,
        include_doors: this.el.querySelector("#filter_doors")?.checked || false,
        include_restaurant: this.el.querySelector("#filter_restaurant")?.checked || false,
    };
    console.log(params)
    // reload data with filters
    await this._loadPage(1, false, params);
},

    _onPrevDay() {
        const current = new Date(dateStart);
        current.setDate(current.getDate() - 1);
        window.location.href = `/my/attendance/?start_day=${current.toISOString().slice(0,10)}`;
    },

    _onNextDay() {
       //const current = new Date(dateStr); 
        const current = new Date(dateStart);

        current.setDate(current.getDate() + 1);
        window.location.href = `/my/attendance/?start_day=${current.toISOString().slice(0,10)}`;
    },

   
   
  



    async _loadPage(page = 1, append = false, filters = {}) {
        // console.log("loadpage", currentPage,"filter", filters);
        if (!filters){
            filters = {
                terminal: Array.from(this.el.querySelector("#filter_terminal")?.selectedOptions).map(opt => opt.value) || false,
                from: this.el.querySelector("#filter_from")?.value || false,
                to: this.el.querySelector("#filter_to")?.value || false,
                include_doors: this.el.querySelector("#filter_doors")?.checked || false,
                include_restaurant: this.el.querySelector("#filter_restaurant")?.checked || false,
            };  
        }

        console.log(`Filters` , filters)

        if (!dateStart && !dateEnd) return;
        const list = this.el.querySelector("#attendance-list");
        if (!list) return console.warn("attendance-list not found in DOM");
    
        const spinnerRow = this.el.querySelector("#attendance-spinner-row");
        if (spinnerRow) spinnerRow.style.display = ""; // show spinner
    
        try {
            const result = await this.rpc(`/my/attendance/json`, {start_day:dateStart, end_day:dateEnd,page, page_size: pageSize,filters, });
            //console.log(result);
            if (result && result.filters){
                this.el.querySelector('#filter_restaurant').value = result.filters?.include_restaurant
                this.el.querySelector('#filter_doors').value = result.filters?.include_doors
               // this.el.querySelector("#filter_terminal")?.selectedOptions).map(opt=>opt.value) || false


                const selectEl = this.el.querySelector('#filter_terminal');
                const selectedValues = Array.isArray(result.filters?.terminal)
                                        ? result.filters.terminal
                                        : (result.filters?.terminal ? [result.filters.terminal] : []);
                
                for (const option of selectEl.options) {
                    option.selected = selectedValues.includes(option.value);
                }
            };

            if (!append) {
                // keep only the spinner row
                list.innerHTML = "";
                list.append(spinnerRow);
            }
    
            if (result && result.portal_data && result.portal_data.length > 0 && result.portal_data[0].length > 0) {
                
                
                result.portal_data[0].forEach(record => {
                    let lastAction = "unknown";
                    if (record.punches && record.punches.length) {
                        const lp = record.punches[record.punches.length - 1];
                        if (lp && Object.prototype.hasOwnProperty.call(lp, "punch_state")) {
                            lastAction = lp.punch_state == 1 ? "check_in" :
                                         lp.punch_state == 2 ? "check_out" : "unknown";
                        } else if (lp && lp.action) {
                            const a = String(lp.action).toLowerCase();
                            lastAction = a.includes("in") ? "check_in" :
                                         a.includes("out") ? "check_out" : "unknown";
                        } else {
                            lastAction = "check_in";
                        }
                    }
    
                    const employeeName = (record.employee_id && record.employee_id.name) ? record.employee_id.name : "";
                    const row = xml`<tr data-empcode="${(record.employee_id.barcode || "").toString().padStart(6, "0")}" data-employee="${employeeName.toLowerCase()}" data-last-action="${lastAction}">
                        <td>${(record.employee_id.barcode || "").toString().padStart(6, "0")}</td>
                        <td>${employeeName}</td>
                        <td>${record.day}</td>
                        <td class="punches">
                            ${(record.punches || []).map(
                                punch => `<span class="badge bg-primary ms-1" ${' '} style="white-space:nowrap">
                                    ${(!punch.terminal_alias ? 'M| ' : '')} 
                                    <span style="color:red">${(punch.sens ==='out' ? '⬆| ' : '')} </span>
                                     <span style="color:green"> ${(punch.sens ==='in' ? '⬇| ' : '')}</span>
                                      ${punch.punch_time.split(" ")[1] || ''}
                                    <i class="fa fa-times text-danger" 
                                    data-action="delete" 
                                    data-id="${punch.id}"></i>
                                </span>`
                            ).join("")}
                        </td>
                        <td class="entrance_punches" ${' '}  style="white-space:nowrap">
                            ${(record.entrance_punches || []).map(
                                punch => `<span class="badge bg-success ms-1">${(!punch.terminal_alias ? 'M| ' : '')} 
                                    <span style="color:red">${(punch.sens ==='out' ? '⬆| ' : '')} </span>
                                     <span style="color:green"> ${(punch.sens ==='in' ? '⬇| ' : '')}</span>
                                     ${punch.punch_time.split(" ")[1]}</span>`
                            ).join("")}
                        </td>
                        <td class="restaurant">
                            ${(record.restaurant || []).map(
                                punch => `<span class="badge bg-warning ms-1">${punch.punch_time.split(" ")[1]}</span>`
                            ).join("")}
                        </td>
                        <!--
                        <td class="exceptions">
                            ${(record.exceptions || []).map(
                                punch => `<span class="badge bg-alert ms-1">${punch}</span>`
                            ).join("")}
                        </td>
                        -->
                        <td>


                       <form   action="/my/attendance/get_punches"  method="post"  target="_blank"  class="d-inline" >
                            <!-- Employee ID -->
                            <input type="hidden" name="emp_id" value="${record.emp_id}" />

                            <!-- Date range -->
                            <input type="hidden" name="start_day" value="${record.day}T00:00" />
                            <input type="hidden" name="end_day" value="${record.day}T23:59" />

                            <!-- Submit button -->
                            <button type="submit" class="btn btn-sm btn-success">
                                <i class="fa fa-list"></i>
                            </button>
    
                        </form>

                            <button class="btn btn-sm btn-info"
                                data-action="show_report"
                                data-empid="${record.emp_id}"
                                data-curdate="${record.day}">
                                <i class="fa fa-file-text"></i>
                            </button>
                            <button class="btn btn-sm btn-success"
                                data-action="add_punch"
                                data-id="${record.id}"
                                data-empid="${record.emp_id}"
                                data-curdate="${record.day}">
                                <i class="fa fa-plus"></i>
                            </button>
                            <button class="btn btn-sm btn-warning"
                                data-action="add_leave"
                                data-empid="${record.employee_id.id}"
                                data-curdate="${record.day}">
                                <i class="fa fa-plane"></i>
                            </button>
                        </td>
                    </tr>`;
                    spinnerRow.insertAdjacentElement("beforebegin", renderToElement(row));
                });
    
                // reapply filters
                this._applyFilter();
            } else {
                currentPage = page;
            }
        } 
        catch(error) {
  console.error(error);} 
        finally {
            if (spinnerRow) spinnerRow.style.display = "none"; // hide spinner when done
        }
    },
    
    // async __loadPage(page = 1, append = false) {
    //         console.log("loadpage",currentPage);

    //     if (!dateStr) return;
    //     const list = this.el.querySelector("#attendance-list");
    //     if (!list) return console.warn("attendance-list not found in DOM");

    //     const result = await this.rpc(`/my/attendance/json/${dateStr}`, { page, page_size: pageSize });
    //     if (!append) list.innerHTML = "";

    //     if (result && result.portal_data && result.portal_data.length > 0 && result.portal_data[0].length > 0) {
    //         result.portal_data[0].forEach(record => {
    //             // compute last action best-effort
    //             let lastAction = "unknown";
    //             if (record.punches && record.punches.length) {
    //                 const lp = record.punches[record.punches.length - 1];
    //                 if (lp && Object.prototype.hasOwnProperty.call(lp, "punch_state")) {
    //                     lastAction = lp.punch_state == 1 ? "check_in" :
    //                                  lp.punch_state == 2 ? "check_out" : "unknown";
    //                 } else if (lp && lp.action) {
    //                     const a = String(lp.action).toLowerCase();
    //                     lastAction = a.includes("in") ? "check_in" :
    //                                  a.includes("out") ? "check_out" : "unknown";
    //                 } else {
    //                     // fallback: if there is at least one punch, assume check_in (you can refine)
    //                     lastAction = "check_in";
    //                 }
    //             }

    //             const employeeName = (record.employee_id && record.employee_id.name) ? record.employee_id.name : "";
    //             const row = xml`<tr data-employee="${employeeName.toLowerCase()}" data-last-action="${lastAction}">
    //                 <td>${(record.employee_id.barcode || "").toString().padStart(6, "0")}</td>
    //                 <td>${employeeName}</td>
    //                 <td class="punches">ssss
    //                     ${(record.punches || []).map(
    //                         punch => `<span class="card badge bg-primary ms-1"> ${(!punch.terminal_alias ? 'M' : 'A')} ${punch.punch_time.split(" ")[1] || '' }
    //                             <i class="fa fa-times text-danger"
    //                                data-action="delete"
    //                                data-id="${punch.id}"/>
    //                           </span>`
    //                     ).join("ssss")}
    //                 </td>
    //                 <td class="entrance_punches">
    //                     ${(record.entrance_punches || []).map(
    //                         punch => `<span class="badge bg-success ms-1">${punch.punch_time.split(" ")[1]}</span>`
    //                     ).join("")}
    //                 </td>
    //                 <td class="restaurant">
    //                     ${(record.restaurant || []).map(
    //                         punch => `<span class="badge bg-warning ms-1">${punch.punch_time.split(" ")[1]}</span>`
    //                     ).join("")}
    //                 </td>
    //                 <td class="exceptions">
    //                     ${(record.exceptions || []).map(
    //                         punch => `<span class="badge bg-alert ms-1">${punch}</span>`
    //                     ).join("")}
    //                 </td>
    //                 <td>
    //                     <button class="btn btn-sm btn-success"
    //                             data-action="add_punch"
    //                             data-id="${record.id}"
    //                             data-empid="${record.emp_id}"
    //                             data-curdate="${dateStr}">
    //                         <i class="fa fa-plus"></i>
    //                     </button>
    //                     <button class="btn btn-sm btn-warning"
    //                             data-action="add_leave"
    //                             data-empid="${record.employee_id.id}"
    //                             data-curdate="${dateStr}">
    //                         <i class="fa fa-plane"></i>
    //                     </button>
    //                 </td>
    //             </tr>`;
    //             list.append(renderToElement(row));
    //         });

    //         // Après ajout des lignes, appliquer le filtre (search/filter)
    //         this._applyFilter();
    //     } else {
    //         currentPage = page;
    //     }
    // },

    // ------------------------------
    // Filtrage / Recherche
    // ------------------------------
    _applyFilter() {
        console.log("filter",currentPage);
        const search = (this.el.querySelector("#attendance_search")?.value || "").trim().toLowerCase();
        const filter = (this.el.querySelector("#attendance_filter")?.value || "all");
        const rows = Array.from(this.el.querySelectorAll("#attendance-list tr"));

        rows.forEach(row => {
            const emp = (row.dataset.employee || "").toLowerCase();
            const emp_code = (row.dataset.empcode || "").toLowerCase();
            const last = (row.dataset.lastAction || "unknown").toLowerCase();
            let show = true;

            if ((search && !emp.includes(search)) || (search && !emp_code.includes(search))) show = false;

            if (filter !== "all") {
                if (filter === "check_in" && last !== "check_in") show = false;
                if (filter === "check_out" && last !== "check_out") show = false;
            }

            row.style.display = show ? "" : "none";
        });
    },

    // ------------------------------
    // Event Handlers
    // ------------------------------
    async _onLoadMore() {
            console.log("loadmore",currentPage);

        await this._loadPage(currentPage, true);
        currentPage++;
    },

    async _onDelete(ev) {
            console.log("delete",currentPage);

        const id = ev.currentTarget.dataset.id;
        this.dialog.add(ConfirmationDialog, {
            title: "Confirm",
            body: markup("<b>Êtes-vous sûr de vouloir supprimer cette entrée ?</b>"),
            confirm: async () => {
                const result = await this.rpc(`/my/attendance/delete/${id}`, { csrf_token: odoo.csrf_token });
                this.dialog.add(ConfirmationDialog, {
                    title: result.status === "success" ? "✅ Success" : "❌ Error",
                    body: result.message,
                });
                if (result.status === "success") {
                    // supprime l'élément parent (badge) — ou recharge la ligne selon le besoin
                    const card = ev.currentTarget.closest(".card");
                    if (card) card.remove();
                }
            },
        });
    },

    async _onGetPunches(ev) {
        console.log("get punch",currentPage);

        const empId = ev.currentTarget.dataset.empid;
        const nowStr = ev.currentTarget.dataset.curdate;
        const day_from = `${nowStr}T00:00`
        const day_to = `${nowStr}T23:59`

        const formHtml = `<div class="text-nowrap">
            <form id="getPunchForm" >
                <label class="fw-bold small">Punch Time</label>
                <input type="datetime-local" name="from" class="form-control form-control-sm" required="1" value="${day_from}T00:00"/>
                <label class="fw-bold small">Punch State</label>
                <input type="datetime-local" name="to" class="form-control form-control-sm"  value="${day_to}T23:59:00"/>
                <label class="fw-bold small">Punch State</label>
                <input type="hidden" name="employee" value="${empId}"/>
                <input type="text" name="test" value="${day_from}"/>

            </form>
            </div>`;

        this.dialog.add(ConfirmationDialog, {
            title: "Get  Punches",
            body: markup(formHtml),
            confirmLabel: "Search",
            confirm: async () => {
                const form = document.getElementById("getPunchForm");
                const payload = {
                    
                    start_day: form.from.value,
                    end_day: form.to.value,
                    emp_id: empId
                };
                try {
                        const result = await this.rpc("/my/attendance/get_punches", payload);
                        const newWindow = window.open();
                        newWindow.document.write(result.html);
//newWindow.document.close();
                    } catch (err) {
                        console.error("Error fetching punches:", err);
                    }   
            },
        });
    },


    async _onShowReport(ev) {
        const empId = ev.currentTarget.dataset.empid;
        const day = ev.currentTarget.dataset.curdate;
        window.open(`/my/attendance/report/${empId}?date=${day}`, "_blank");
    },
    async _onAddPunch(ev) {
            console.log("add punch",currentPage);

        const empId = ev.currentTarget.dataset.empid;
        const nowStr = ev.currentTarget.dataset.curdate;
        const formHtml = `<div class="text-nowrap">
            <form id="manualPunchForm" >
                <label class="fw-bold small">Punch Time</label>
                <input type="datetime-local" name="punch_time" class="form-control form-control-sm" required="1" value="${nowStr}T00:00"/>
                <label class="fw-bold small">Punch State</label>
                <select name="punch_state" class="form-select form-select-sm" required="1">
                    <option value="1">Check-In</option>
                    <option value="2">Check-Out</option>
                </select>
                <label class="fw-bold small">Reason</label>
                <input type="text" name="apply_reason" class="form-control form-control-sm" placeholder="Reason (optional)"/>
                            <input type="hidden" name="employee" value="${empId}"/>

            </form></div>`;

        this.dialog.add(ConfirmationDialog, {
            title: "Add Manual Punch",
            body: markup(formHtml),
            confirmLabel: "Save",
            confirm: async () => {
                const form = document.getElementById("manualPunchForm");
                const payload = {
                    employee: empId,
                    punch_time: form.punch_time.value,
                    punch_state: form.punch_state.value,
                    apply_reason: form.apply_reason.value || "",
                    work_code: "",
                };

                const result = await this.rpc("/my/attendance/add_punch", payload);
                this.dialog.add(ConfirmationDialog, {
                    title: result.status === "success" ? "✅ Created" : "❌ Error",
                    body: result.message,
                    confirm: () => {
                        if (result.status === "success") {
                            const row = ev.currentTarget.closest("tr");
                            if (row) {
                                row.querySelector("td.punches").insertAdjacentHTML(
                                    "beforeend",
                                    `<span class="badge bg-success ms-1">${payload.punch_time.slice(11, 16)}</span>`
                                );
                                // recalculer last-action si nécessaire (ici on met check_in si punch_state==1)
                                if (payload.punch_state == "1") row.dataset.lastAction = "check_in";
                                if (payload.punch_state == "2") row.dataset.lastAction = "check_out";
                                this._applyFilter();
                            }
                        }
                    },
                });
            },
        });
    },

    async _onAddLeave(ev) {
            console.log("add leave",currentPage);

        const empId = ev.currentTarget.dataset.empid;
        const nowStr = ev.currentTarget.dataset.curdate;
        const formHtml = `<div class="text-nowrap">
            <form id="leaveForm">
                <input type="hidden" name="employee" value="${empId}"/>
                <label class="fw-bold small">Start</label>
                <input type="datetime-local" name="start_time" class="form-control form-control-sm" required value="${nowStr}T00:00"/>
                <label class="fw-bold small">End</label>
                <input type="datetime-local" name="end_time" class="form-control form-control-sm" required value="${nowStr}T23:59"/>
                <label class="fw-bold small">Reason</label>
                <input type="text" name="apply_reason" class="form-control form-control-sm" placeholder="Reason (optional)"/>
            </form></div>`;

        this.dialog.add(ConfirmationDialog, {
            title: "Add Leave",
            body: markup(formHtml),
            confirmLabel: "Save",
            confirm: async () => {
                const form = document.getElementById("leaveForm");
                const payload = {
                    employee: empId,
                    start_time: form.start_time.value,
                    end_time: form.end_time.value,
                    apply_reason: form.apply_reason.value || "",
                    pay_code: 12,
                    work_code: "",
                };

                const result = await this.rpc("/my/leaves/add_leaves", payload);
                this.dialog.add(ConfirmationDialog, {
                    title: result.status === "success" ? "✅ Created" : "❌ Error",
                    body: result.message,
                });
            },
        });
    },
});


// import { Component } from "@odoo/owl";
// import { registry } from "@web/core/registry"

// export class AttendanceLine extends Component {
//     static template = "nabi_hr.portal_attendance_line";
//     static props = {};
// }

// registry.category("public_components").add("nabi_hr.portal_attendance_line", AttendanceLine);
