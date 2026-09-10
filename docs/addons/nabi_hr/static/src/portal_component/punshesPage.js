
/* @odoo-module */
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';
import { xml } from "@odoo/owl";
import { renderToElement } from "@web/core/utils/render";
const { markup } = require("@odoo/owl");
import { AttendancePortalLine } from "./attendanceLine";



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

publicWidget.registry.PunchesFilter = publicWidget.Widget.extend({
    selector: '#punches-page',  // wrapper around your filter and table

    events :{
        "click [data-action=delete]"        : "_onDelete",
        "click [data-action=add_punch]"     : "_onAddPunch",
        "click [data-action=add_leave]"     : "_onAddLeave",
         "click #filter_btn"                 : "_onFilter",
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
                console.log("add leave");
    
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

    start() {
        const filterBtn = this.el.querySelector('#filter_btn');
        if (filterBtn) {
            filterBtn.addEventListener('click', this._onFilter.bind(this));
        }
    },

    _onFilter(ev) {
        ev.preventDefault();

        const empId = Array.from(this.el.querySelector("#filter_employee")?.selectedOptions).map(opt=>opt.value) || false;
        //this.el.querySelector('#filter_employee')?.value || '';

        const fromDate = this.el.querySelector('#filter_from')?.value;
        const toDate = this.el.querySelector('#filter_to')?.value;
        // const Terminal = this.el.querySelector('#filter_terminal')?.value;
        const Terminal = Array.from(this.el.querySelector("#filter_terminal")?.selectedOptions).map(opt=>opt.value) || false;

        

        // create a form dynamically to submit POST
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/my/attendance/get_punches';
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
});

