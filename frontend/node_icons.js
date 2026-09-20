/**
 * High-Precision Vector Icon Drawing Routines for Physical Fleet Nodes.
 * Renders recognizable hardware form-factors onto HTML5 Canvas:
 * - Drone: Aerial Quadcopter with spinning rotors and camera gimbal
 * - Server: Edge AI GPU Rack with blade slots and LED telemetry
 * - Rover: All-terrain Mobile Ground Robot (UGV) with LiDAR dome
 * - Arm: Articulated Industrial Robotic Manipulator with gripper
 * - Chip: Edge TPU / Neural Processing Coprocessor
 */

const NodeIconRenderer = {
    /**
     * Draws an Autonomous Aerial Quadcopter Drone.
     */
    drawDrone(ctx, cx, cy, size = 38, color = "#2563EB", animTick = 0) {
        ctx.save();
        ctx.translate(cx, cy);

        const r = size / 2;
        const armLen = r * 0.75;
        const rotorR = r * 0.38;

        // Diagonal arms
        ctx.strokeStyle = "#475569";
        ctx.lineWidth = 2.4;
        ctx.lineCap = "round";

        const angles = [Math.PI / 4, 3 * Math.PI / 4, 5 * Math.PI / 4, 7 * Math.PI / 4];
        angles.forEach(ang => {
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(Math.cos(ang) * armLen, Math.sin(ang) * armLen);
            ctx.stroke();
        });

        // 4 Rotors & Spinning Propellers
        angles.forEach((ang, i) => {
            const rx = Math.cos(ang) * armLen;
            const ry = Math.sin(ang) * armLen;

            // Motor mount hub
            ctx.fillStyle = "#1E293B";
            ctx.beginPath();
            ctx.arc(rx, ry, 3.5, 0, Math.PI * 2);
            ctx.fill();

            // Rotor Guard Ring
            ctx.strokeStyle = "rgba(148, 163, 184, 0.4)";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(rx, ry, rotorR, 0, Math.PI * 2);
            ctx.stroke();

            // Spinning Propeller Blades
            ctx.save();
            ctx.translate(rx, ry);
            const spin = (animTick * 0.35 * (i % 2 === 0 ? 1 : -1)) + (i * Math.PI / 2);
            ctx.rotate(spin);

            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.ellipse(0, 0, rotorR * 0.95, 2, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        });

        // Central Drone Chassis Body
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(-r * 0.35, -r * 0.35, r * 0.7, r * 0.7, 4);
        ctx.fill();
        ctx.stroke();

        // Sensor Gimbal Eye / Lens
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, r * 0.18, 0, Math.PI * 2);
        ctx.fill();

        // Pulsing navigation beacon
        ctx.fillStyle = "#10B981";
        ctx.beginPath();
        ctx.arc(0, -r * 0.35, 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
    },

    /**
     * Draws an Edge AI GPU Server Rack.
     */
    drawServer(ctx, cx, cy, size = 36, color = "#10B981", animTick = 0) {
        ctx.save();
        ctx.translate(cx, cy);

        const w = size * 0.85;
        const h = size * 0.75;
        const x = -w / 2;
        const y = -h / 2;

        // Server Rack Chassis Box
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, 4);
        ctx.fill();
        ctx.stroke();

        // Blade Bays
        const bayH = (h - 8) / 3;
        for (let i = 0; i < 3; i++) {
            const bayY = y + 4 + (i * bayH);
            ctx.fillStyle = "#F1F5F9";
            ctx.strokeStyle = "#CBD5E1";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(x + 4, bayY, w - 8, bayH - 2, 2);
            ctx.fill();
            ctx.stroke();

            // Ventilation slits
            ctx.strokeStyle = "#94A3B8";
            ctx.lineWidth = 1.2;
            for (let v = 0; v < 4; v++) {
                const vx = x + 8 + (v * 4.5);
                ctx.beginPath();
                ctx.moveTo(vx, bayY + 2);
                ctx.lineTo(vx, bayY + bayH - 4);
                ctx.stroke();
            }

            // Blinking activity LEDs
            const ledOn = Math.sin(animTick * 0.2 + i * 2) > 0;
            ctx.fillStyle = ledOn ? color : "#94A3B8";
            ctx.beginPath();
            ctx.arc(x + w - 10, bayY + bayH / 2 - 1, 2, 0, Math.PI * 2);
            ctx.fill();

            // Secondary Power LED
            ctx.fillStyle = "#10B981";
            ctx.beginPath();
            ctx.arc(x + w - 16, bayY + bayH / 2 - 1, 1.6, 0, Math.PI * 2);
            ctx.fill();
        }

        ctx.restore();
    },

    /**
     * Draws a Mobile Ground Robot / All-Terrain Rover (UGV).
     */
    drawRover(ctx, cx, cy, size = 36, color = "#8B5CF6", animTick = 0) {
        ctx.save();
        ctx.translate(cx, cy);

        const w = size * 0.82;
        const h = size * 0.58;
        const x = -w / 2;
        const y = -h / 2;

        // 4 Heavy-Duty Wheels / Caterpillar Treads
        ctx.fillStyle = "#1E293B";
        ctx.strokeStyle = "#64748B";
        ctx.lineWidth = 1;

        // Top-left and Top-right wheels
        ctx.beginPath();
        ctx.roundRect(x - 3, y - 2, 6, 9, 2);
        ctx.fill();
        ctx.stroke();

        ctx.beginPath();
        ctx.roundRect(x + w - 3, y - 2, 6, 9, 2);
        ctx.fill();
        ctx.stroke();

        // Bottom-left and Bottom-right wheels
        ctx.beginPath();
        ctx.roundRect(x - 3, y + h - 7, 6, 9, 2);
        ctx.fill();
        ctx.stroke();

        ctx.beginPath();
        ctx.roundRect(x + w - 3, y + h - 7, 6, 9, 2);
        ctx.fill();
        ctx.stroke();

        // Main Rover Chassis
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(x + 2, y, w - 4, h, 4);
        ctx.fill();
        ctx.stroke();

        // Solar/Power Panel Strip
        ctx.fillStyle = "#E2E8F0";
        ctx.fillRect(x + 5, y + 4, w - 10, 5);

        // Rotating LiDAR Turret Dome
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, 5.5, 0, Math.PI * 2);
        ctx.fill();

        // LiDAR Scanning Beam line
        const sweep = (animTick * 0.12) % (Math.PI * 2);
        ctx.strokeStyle = "#FFFFFF";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.cos(sweep) * 5, Math.sin(sweep) * 5);
        ctx.stroke();

        // Antenna with signal wave
        ctx.strokeStyle = "#475569";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x + w - 6, y);
        ctx.lineTo(x + w - 6, y - 8);
        ctx.stroke();

        ctx.fillStyle = "#EF4444";
        ctx.beginPath();
        ctx.arc(x + w - 6, y - 8, 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
    },

    /**
     * Draws an Articulated Industrial Robotic Manipulator Arm.
     */
    drawRoboticArm(ctx, cx, cy, size = 36, color = "#EC4899", animTick = 0) {
        ctx.save();
        ctx.translate(cx, cy);

        // Pedestal base
        ctx.fillStyle = "#1E293B";
        ctx.beginPath();
        ctx.roundRect(-12, 10, 24, 6, 2);
        ctx.fill();

        // Shoulder joint
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 8, 4.5, 0, Math.PI * 2);
        ctx.fill();

        // Kinematic arm motion
        const angle1 = -Math.PI / 3 + Math.sin(animTick * 0.08) * 0.15;
        const angle2 = Math.PI / 4 + Math.cos(animTick * 0.08) * 0.2;

        const l1 = 13;
        const elbowX = Math.cos(angle1) * l1;
        const elbowY = 8 + Math.sin(angle1) * l1;

        // Base Arm Link
        ctx.strokeStyle = "#334155";
        ctx.lineWidth = 3.5;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(0, 8);
        ctx.lineTo(elbowX, elbowY);
        ctx.stroke();

        // Elbow joint
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(elbowX, elbowY, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Forearm Link
        const l2 = 12;
        const wristX = elbowX + Math.cos(angle1 + angle2) * l2;
        const wristY = elbowY + Math.sin(angle1 + angle2) * l2;

        ctx.strokeStyle = color;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(elbowX, elbowY);
        ctx.lineTo(wristX, wristY);
        ctx.stroke();

        // Gripper End-Effector
        ctx.strokeStyle = "#0F172A";
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.arc(wristX, wristY, 2.5, 0, Math.PI * 2);
        ctx.stroke();

        // Gripper claws
        ctx.beginPath();
        ctx.moveTo(wristX - 3, wristY - 3);
        ctx.lineTo(wristX + 3, wristY - 3);
        ctx.lineTo(wristX + 4, wristY - 7);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(wristX - 3, wristY - 3);
        ctx.lineTo(wristX - 4, wristY - 7);
        ctx.stroke();

        ctx.restore();
    },

    /**
     * Draws an Edge TPU / Coprocessor Chip.
     */
    drawChip(ctx, cx, cy, size = 34, color = "#06B6D4", animTick = 0) {
        ctx.save();
        ctx.translate(cx, cy);

        const s = size * 0.65;
        const half = s / 2;

        // External connector pins
        ctx.strokeStyle = "#94A3B8";
        ctx.lineWidth = 1.5;
        const pinLen = 3.5;
        const numPins = 4;
        const step = s / (numPins + 1);

        for (let i = 1; i <= numPins; i++) {
            const p = -half + i * step;
            // Top pins
            ctx.beginPath(); ctx.moveTo(p, -half); ctx.lineTo(p, -half - pinLen); ctx.stroke();
            // Bottom pins
            ctx.beginPath(); ctx.moveTo(p, half); ctx.lineTo(p, half + pinLen); ctx.stroke();
            // Left pins
            ctx.beginPath(); ctx.moveTo(-half, p); ctx.lineTo(-half - pinLen, p); ctx.stroke();
            // Right pins
            ctx.beginPath(); ctx.moveTo(half, p); ctx.lineTo(half + pinLen, p); ctx.stroke();
        }

        // Silicon package body
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(-half, -half, s, s, 3);
        ctx.fill();
        ctx.stroke();

        // Die core
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.roundRect(-half * 0.55, -half * 0.55, s * 0.55, s * 0.55, 2);
        ctx.fill();

        // Pulse dot
        ctx.fillStyle = "#FFFFFF";
        ctx.beginPath();
        ctx.arc(0, 0, 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
    },

    /**
     * Universal dispatcher that draws the appropriate node icon by type.
     */
    drawNodeIcon(ctx, nodeType, cx, cy, size, color, animTick = 0) {
        switch (nodeType) {
            case "drone":
                this.drawDrone(ctx, cx, cy, size, color, animTick);
                break;
            case "server":
                this.drawServer(ctx, cx, cy, size, color, animTick);
                break;
            case "rover":
                this.drawRover(ctx, cx, cy, size, color, animTick);
                break;
            case "arm":
                this.drawRoboticArm(ctx, cx, cy, size, color, animTick);
                break;
            case "chip":
                this.drawChip(ctx, cx, cy, size, color, animTick);
                break;
            default:
                this.drawDrone(ctx, cx, cy, size, color, animTick);
                break;
        }
    }
};

window.NodeIconRenderer = NodeIconRenderer;
