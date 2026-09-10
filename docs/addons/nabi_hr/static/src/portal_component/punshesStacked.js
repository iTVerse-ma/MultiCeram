
/* @odoo-module */
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';
import { xml } from "@odoo/owl";
import { renderToElement } from "@web/core/utils/render";
const { markup } = require("@odoo/owl");
import { AttendancePortalLine } from "./attendanceLine";

const {useState } = require("@odoo/owl");
import { useService } from "@web/core/utils/hooks";




// ##############################
// Global variables
// ##############################
// let   currentPage   = 1;
// const pageSize      = 100;
// const match         = window.location.pathname.match(/\/my\/attendance\/(\d{4}-\d{2}-\d{2})/);
// let   dateStr       = match ? match[1] : null;

// ##############################
// Attendance Widget
// ##############################


// import publicWidget from 'web.public.widget';

publicWidget.registry.XLSXExport = publicWidget.Widget.extend({
    selector: '.o_portal_wrap',  // wrapper around your filter and table

    events :{
        
        "click [data-action=export_xlsx]"   : "_onExport",
       


          
    },

   

    _onExport() {
        if (typeof XLSX === "undefined") {
            console.error("SheetJS not loaded");
            return;
        }
        const table = this.el.querySelector("table");
        this._tableToXLSX(table, "export.xlsx");
    },
    async _tableToXLSX(table, filename) {
        const wb = XLSX.utils.book_new();
        const ws = {};
        const merges = [];
        const occupied = {};
        let rowIndex = 0;

        [...table.rows].forEach(row => {
            let colIndex = 0;

            [...row.cells]
                .filter(td => !td.classList.contains("no-export"))
                .forEach(cell => {

                    while (occupied[`${rowIndex}:${colIndex}`]) colIndex++;

                    const value = cell.innerText.trim();
                    const colspan = cell.colSpan || 1;
                    const rowspan = cell.rowSpan || 1;

                    const ref = XLSX.utils.encode_cell({ r: rowIndex, c: colIndex });
                    ws[ref] = { v: value, t: "s" };

                    if (colspan > 1 || rowspan > 1) {
                        merges.push({
                            s: { r: rowIndex, c: colIndex },
                            e: { r: rowIndex + rowspan - 1, c: colIndex + colspan - 1 }
                        });
                    }

                    for (let r = 0; r < rowspan; r++) {
                        for (let c = 0; c < colspan; c++) {
                            occupied[`${rowIndex + r}:${colIndex + c}`] = true;
                        }
                    }

                    colIndex += colspan;
                });

            rowIndex++;
        });

        ws["!ref"] = XLSX.utils.encode_range({
            s: { r: 0, c: 0 },
            e: { r: rowIndex, c: 50 }
        });

        ws["!merges"] = merges;

        XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
        XLSX.writeFile(wb, filename);
    },
});


publicWidget.registry.StackedPunchesFilter = publicWidget.Widget.extend({
    selector: '#stacked-punches-page',  // wrapper around your filter and table

    events :{
        "click [data-action=delete]"        : "_onDelete",
        "click [data-action=copy]"          : "_onCopy",
        "click [data-action=add_punch]"     : "_onAddPunch",
        "click [data-action=add_leave]"     : "_onAddLeave",
        "click #filter_btn"                 : "_onFilter",
        "input #input_employee"             : "_onInputEmployee",
        "click [data-action=export_xlsx]"   : "_onExport",
        "click [data-action=soummettre],[data-action=add_jour_repos]"   : "_onAddJourRepos",
        "click .toggleButtons,div:has(>.toggleButtons),.rowToggle"      : "_toggleButtons",


          
    },

   

    _onExport() {
        if (typeof XLSX === "undefined") {
            console.error("SheetJS not loaded");
            return;
        }
        const table = this.el.querySelector("table");
        this._tableToXLSX(table, "export.xlsx");
    },
    async _tableToXLSX(table, filename) {
        const wb = XLSX.utils.book_new();
        const ws = {};
        const merges = [];
        const occupied = {};
        let rowIndex = 0;

        [...table.rows].forEach(row => {
            let colIndex = 0;

            [...row.cells]
                .filter(td => !td.classList.contains("no-export"))
                .forEach(cell => {

                    while (occupied[`${rowIndex}:${colIndex}`]) colIndex++;

                    const value = cell.innerText.trim();
                    const colspan = cell.colSpan || 1;
                    const rowspan = cell.rowSpan || 1;

                    const ref = XLSX.utils.encode_cell({ r: rowIndex, c: colIndex });
                    ws[ref] = { v: value, t: "s" };

                    if (colspan > 1 || rowspan > 1) {
                        merges.push({
                            s: { r: rowIndex, c: colIndex },
                            e: { r: rowIndex + rowspan - 1, c: colIndex + colspan - 1 }
                        });
                    }

                    for (let r = 0; r < rowspan; r++) {
                        for (let c = 0; c < colspan; c++) {
                            occupied[`${rowIndex + r}:${colIndex + c}`] = true;
                        }
                    }

                    colIndex += colspan;
                });

            rowIndex++;
        });

        ws["!ref"] = XLSX.utils.encode_range({
            s: { r: 0, c: 0 },
            e: { r: rowIndex, c: 50 }
        });

        ws["!merges"] = merges;

        XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
        XLSX.writeFile(wb, filename);
    },

    setup: function() {
        this.orm = useService("orm");
        console.log("setup", this.orm)

        this.state = useState({
            visible: {} // { record_id: true/false }
        });
    },

    async _onDelete(ev) {

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
                    this._onFilter()
                }
            },
        });
    },

    async _onCopy(ev) {

        const id = ev.currentTarget.dataset.id;
        this.dialog.add(ConfirmationDialog, {
            title: "Confirm",
            body: markup("<b>Êtes-vous sûr de vouloir copier cette entrée ?</b>"),
            confirm: async () => {
                const result = await this.rpc(`/my/attendance/copy/${id}`, { csrf_token: odoo.csrf_token });
                this.dialog.add(ConfirmationDialog, {
                    title: result.status === "success" ? "✅ Success" : "❌ Error",
                    body: result.message,
                });
                if (result.status === "success") {
                    // supprime l'élément parent (badge) — ou recharge la ligne selon le besoin
                    //const card = ev.currentTarget.closest(".card");
                    //if (card) card.remove();
                    this._onFilter()
                }
            },
        });
    },
   

    _toggleButtons(ev) {
        ev.stopPropagation();
        // toggle only inside this div
            const btns = ev.currentTarget?.querySelector('.btns');
            const btns2 = ev.currentTarget.nextElementSibling?.closest('.btns');
            const detail = ev.currentTarget?.querySelectorAll('.detail');

            if (btns) {
                btns.classList.toggle('d-none');
                // btns.classList.toggle('d-inline-block');
                 };
                  if (btns2) {
                btns2.classList.toggle('d-none');
                // btns.classList.toggle('d-inline-block');
                 };
            if (detail) {
                detail.forEach((x)=>x.classList.toggle('d-none'));
                // detail.classList.toggle('d-block');
           
        }

          //  console.log(ev.currentTarget);
        },  

    init() {
        //console.log("init",currentPage);
        //this._super(...arguments);
        this.dialog = this.bindService("dialog");
        this.rpc = rpc;
        this.orm = this.bindService("orm");

        this._refreshInterval = null;
        // this.initDatePickers();
        // this.bindEvents();
        // this.initOdooDatePickers();
    },
    async _onAddJourRepos(ev){
        const empId     = ev.currentTarget.dataset.empid;
        const nowStr    = ev.currentTarget.dataset.curdate;
        const mode      = ev.currentTarget.dataset.mode;
        const hs    = ev.currentTarget.dataset.hs;
        const payload = {
            'employee': empId,
            'date': nowStr,
            'mode': mode, 
            'hs': hs
        };
        const result = await this.rpc("/my/attendance/add_jour_repos", payload);
        this.dialog.add(ConfirmationDialog, {
            title: result.status === "success" ? "✅ Created" : "❌ Error",
            body: result.message,
            confirm: () => {
                if (result.status === "success") {
                        this._onFilter();
                    // const row = ev.currentTarget.closest("tr");
                    // if (row) {
                    //     console.log(row)
                    //     row.querySelector("td.punches").insertAdjacentHTML(
                    //         "beforeend",
                    //         `<span class="badge bg-success ms-1">${payload.punch_time.slice(11, 16)}</span>`
                    //     );
                    //     // recalculer last-action si nécessaire (ici on met check_in si punch_state==1)
                    //     if (payload.punch_state == "1") row.dataset.lastAction = "check_in";
                    //     if (payload.punch_state == "2") row.dataset.lastAction = "check_out";
                        
                    // }
                }
            },
        });
    },

    async _onAddPunch(ev) {
                console.log("add punch");
    
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
                                 this._onFilter();
                                // const row = ev.currentTarget.closest("tr");
                                // if (row) {
                                //     console.log(row)
                                //     row.querySelector("td.punches").insertAdjacentHTML(
                                //         "beforeend",
                                //         `<span class="badge bg-success ms-1">${payload.punch_time.slice(11, 16)}</span>`
                                //     );
                                //     // recalculer last-action si nécessaire (ici on met check_in si punch_state==1)
                                //     if (payload.punch_state == "1") row.dataset.lastAction = "check_in";
                                //     if (payload.punch_state == "2") row.dataset.lastAction = "check_out";
                                   
                                // }
                            }
                        },
                    });
                },
            });
        },
        async loadLeaveTypes() {


            const leaveTypes = await this.orm.call("hr.leave.type", "search_read", [[],  ["id", "name"]   ]);

            

            console.log(leaveTypes);
            return leaveTypes;
        },
     
        async _onAddLeave(ev) {
                console.log("add leave",ev);
    
            const empId = ev.currentTarget.dataset.empid;
            const nowStr = ev.currentTarget.dataset.curdate;
            const leaveTypes = await this.loadLeaveTypes();
            console.log(leaveTypes);
            
            
            const optionsHtml = leaveTypes.map(lt => `<option value="${lt.id}">${lt.name}</option>` ).join("");
            const formHtml = `<div class="text-nowrap">
                <form id="leaveForm">
                    <input type="hidden" name="employee" value="${empId}"/>
                    <label class="fw-bold small">Start</label>
                    <input type="datetime-local" name="start_time" class="form-control form-control-sm" required value="${nowStr}T00:00"/>
                    <label class="fw-bold small">End</label>
                    <input type="datetime-local" name="end_time" class="form-control form-control-sm" required value="${nowStr}T23:59"/>
                    <div class="mb-3">
                        <label class="form-label fw-bold">Type de congé</label>
                        <select name="holiday_status_id" class="form-select form-control-lg">
                                ${optionsHtml}
                                
                       
                            </select>
                    </div>
                    
                    
                    
                    <label class="fw-bold small">Reason</label>
                    <input type="text" name="apply_reason" class="form-control form-control-sm" placeholder="Reason (optional)"/>
                </form></div>`;

            // const formHtml = ev.target.closest("#leaveForm");
            // console.log(formHtml);
    
            this.dialog.add(ConfirmationDialog, {
                title: "Add Leave",
                body: markup(formHtml),
                confirmLabel: "Save",
                confirm: async (eev) => {
                    const modal = document.querySelector(".o_dialog");
                    const form = modal.querySelector("#leaveForm");

                    if (!form) {
                        console.error("Form not found");
                        return;
                    }

                    const payload = {
                        emp_code        : empId,
                        start_time      : form.start_time.value,
                        end_time        : form.end_time.value,
                        holiday_status_id: form.holiday_status_id.value,
                        apply_reason    : form.apply_reason.value || "",
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

    // start() {
    //     const filterBtn = this.el.querySelector('#filter_btn');
    //     if (filterBtn) {
    //         filterBtn.addEventListener('click', this._onFilter.bind(this));
    //     }
    // },

    _onFilter(ev) {
        //ev.preventDefault();

        const empId = Array.from(this.el.querySelector("#filter_employee")?.selectedOptions).map(opt=>opt.value) || false;
        //this.el.querySelector('#filter_employee')?.value || '';

        const fromDate = this.el.querySelector('#filter_from')?.value;
        const toDate = this.el.querySelector('#filter_to')?.value;
        // const Terminal = this.el.querySelector('#filter_terminal')?.value;
        const Terminal = Array.from(this.el.querySelector("#filter_terminal")?.selectedOptions).map(opt=>opt.value) || false;

        

        // create a form dynamically to submit POST
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/my/attendance/get_punch_stacked';
        //form.target = '_blank'; // open in new tab if you want

        const addInput = (name, value) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            form.appendChild(input);
        };

        addInput('terminal_ids', Terminal);
        addInput('emp_id', empId);
        addInput('start_day', fromDate + 'T00:00');
        addInput('end_day', toDate + 'T23:59');

        document.body.appendChild(form);
        form.submit();
        form.remove();
    },


    _onInputEmployee(ev){
        ev.stopPropagation();
        
        const input = this.el.querySelector("#input_employee");
        const select = this.el.querySelector("#filter_employee");

        // Sauvegarde des options d'origine

        
           const query = input.value.toLowerCase();

            const opt = Array.from(select.options).find(o =>
                o.value.toLowerCase() === query ||
                o.text.toLowerCase().includes(query)
            );

            if (opt) select.value = opt.value;
            
    },
});

