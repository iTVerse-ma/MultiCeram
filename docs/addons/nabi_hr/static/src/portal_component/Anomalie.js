
/* @odoo-module */
import { ConfirmationDialog } from '@web/core/confirmation_dialog/confirmation_dialog';
import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';
import { xml } from "@odoo/owl";
import { renderToElement } from "@web/core/utils/render";
const { markup } = require("@odoo/owl");
import { AttendancePortalLine } from "./attendanceLine";

const {useState } = require("@odoo/owl");



publicWidget.registry.EnhancedPortalTable = publicWidget.Widget.extend({
    selector: "#AnomalieTableWrapper",   // ton wrapper principal
    start: function () {
        if (!this.el) return this._super.apply(this, arguments);

        this.table = this.el.querySelector("#myTable");
        this.tbody = this.table.querySelector("tbody");
        this.allRows = [...this.tbody.rows];
        this.filteredRows = [...this.allRows];

        this.page = 1;
        this.pageSize = parseInt(this.el.querySelector("#page_size")?.value || 10);

        this._bindEvents();
        this.renderTable();

        return this._super.apply(this, arguments);
    },

    debounce: function (fn, delay = 200) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    },

    _bindEvents: function () {
        const globalSearch = this.el.querySelector("#global_search");
        if (globalSearch) {
            globalSearch.addEventListener("input", this.debounce(ev => {
                const q = ev.target.value.toLowerCase();
                this.filteredRows = this.allRows.filter(row =>
                    row.textContent.toLowerCase().includes(q)
                );
                this.page = 1;
                this.renderTable();
            }, 250));

            const clearBtn = this.el.querySelector("#clear_search");
            clearBtn?.addEventListener("click", () => {
                globalSearch.value = "";
                this.filteredRows = [...this.allRows];
                this.page = 1;
                this.renderTable();
            });
        }

        // Column filter toggles
        this.el.querySelectorAll(".filter-btn").forEach((btn, i) => {
            btn.addEventListener("click", () => {
                const input = btn.closest("th").querySelector(".col-filter");
                input.classList.toggle("d-none");
                if (!input.classList.contains("d-none")) input.focus();
            });
        });

        this.el.querySelectorAll(".col-filter").forEach((input, colIndex) => {
            input.addEventListener("input", this.debounce(ev => {
                const q = ev.target.value.toLowerCase();
                this.filteredRows = this.allRows.filter(row =>{

                    
                    
                    if (ev.target.closest('th').dataset?.sort == 'number'){
                      return q?row.cells[colIndex].textContent.trim()==q:true
                    }else{

                     return  q!=='-'?row.cells[colIndex].textContent.toLowerCase().includes(q):true
                    }
            });
                this.page = 1;
                this.renderTable();
            }, 200));
        });

        // Sort buttons
        this.el.querySelectorAll(".sort-btn").forEach((btn, i) => {
            btn.addEventListener("click", () => this.sortColumn(btn.closest("th"), i));
        });

        // Page size selector
        this.el.querySelector("#page_size")?.addEventListener("change", ev => {
            this.pageSize = parseInt(ev.target.value);
            this.page = 1;
            this.renderTable();
        });
    },

    renderTable: function () {
        this.tbody.innerHTML = "";

        if (this.pageSize === -1) {
            this.filteredRows.forEach(r => this.tbody.appendChild(r));
            this.renderPager();
            return;
        }

        const start = (this.page - 1) * this.pageSize;
        const end = start + this.pageSize;
        const slice = this.filteredRows.slice(start, end);
        slice.forEach(r => this.tbody.appendChild(r));

        this.renderPager();
    },

    renderPager: function () {
        const pager = this.el.querySelector("#pager");
        if (!pager) return;
        pager.innerHTML = "";

        if (this.pageSize === -1) return;

        const pages = Math.ceil(this.filteredRows.length / this.pageSize);

        const makeButton = (num, text) => {
            const btn = document.createElement("button");
            btn.textContent = text ?? num;
            btn.className = num === this.page ? "active" : "";
            btn.onclick = () => { this.page = num; this.renderTable(); };
            return btn;
        };

        // Prev button
        if (this.page > 1) pager.appendChild(makeButton(this.page - 1, "Prev"));

        // Simple pager: first 6 + last 3 + dots
        const firstPages = 6;
        const lastPages = 3;

        for (let i = 1; i <= Math.min(firstPages, pages); i++) pager.appendChild(makeButton(i));
        if (this.page > firstPages + 1 && pages > firstPages + lastPages) pager.appendChild(this.createDots());
        if (this.page > firstPages && this.page <= pages - lastPages) {
            for (let i = this.page - 1; i <= this.page + 1; i++) {
                if (i > firstPages && i < pages - lastPages + 1) pager.appendChild(makeButton(i));
            }
            pager.appendChild(this.createDots());
        }
        for (let i = pages - lastPages + 1; i <= pages; i++) {
            if (i > firstPages) pager.appendChild(makeButton(i));
        }

        // Next button
        if (this.page < pages) pager.appendChild(makeButton(this.page + 1, "Next"));
    },

    createDots: function () {
        const span = document.createElement("span");
        span.textContent = "…";
        span.className = "dots";
        return span;
    },

    sortColumn: function (th, colIndex) {
        const type = th.dataset.sort;
        const asc = !th.classList.contains("sorted-asc");

        this.el.querySelectorAll("th").forEach(h => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(asc ? "sorted-asc" : "sorted-desc");

        this.filteredRows.sort((a, b) => {
            let A = a.cells[colIndex].textContent.trim();
            let B = b.cells[colIndex].textContent.trim();

            if (type === "number") {
                const nA = Number(A) || 0;
                const nB = Number(B) || 0;
                return asc ? nA - nB : nB - nA;
            }

            return asc
                ? A.localeCompare(B, undefined, { numeric: true })
                : B.localeCompare(A, undefined, { numeric: true });
        });

        this.page = 1;
        this.renderTable();
    },

});