/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class AttendancePortalLine extends Component {
    static template = "nabi_hr.PortalAttendanceLine";
    static props = ["punches"];
  
    start() {
        
        console.log("✅ AttendancePortalLine started:", this.props.record);
    }
    setup() {
        this.state = useState({
            isEditing: false,
            isDisabled: false,
        });
        console.log("✅ AttendancePortalLine setup:", this.props.record);
    }
}

