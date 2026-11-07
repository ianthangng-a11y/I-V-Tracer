
#!/usr/bin/env python3
"""
Vẽ đặc tuyến I-V realtime từ UART (macOS).

Chức năng:
- Nhấn nút RESET trên board -> sweep mới -> đồ thị tự xóa và vẽ lại.
- Tự kết nối lại nếu cổng Serial bị mất.
- Mỗi lần sweep xong ("SWEEP DONE") tự lưu CSV.
- Hiển thị popup nếu INA219 BUS_OK = 0.
- Chỉ hiển thị một popup cho mỗi đợt lỗi liên tục.

Cài đặt:
    pip3 install pyserial matplotlib

Chạy:
    python3 iv_plot_live.py

    python3 iv_plot_live.py -b 9600 -p /dev/cu.usbmodem1103

Đóng cửa sổ đồ thị để thoát.
"""

import argparse
import csv
import glob
import re
from datetime import datetime

import matplotlib.pyplot as plt
import serial
import serial.tools.list_ports

import tkinter as tk
from tkinter import messagebox


# ============================================================
# 1. REGEX: PHÂN TÍCH DỮ LIỆU UART
# ============================================================

LINE_RE = re.compile(
    r"V_PA4=(?P<vpa4>[-\d.]+)\s*V.*?"
    r"V_PA0_RAW=(?P<raw>\d+).*?"
    r"V_PA0=(?P<vpa0>[-\d.]+)\s*V.*?"
    r"I=(?P<i>[-\d.]+)\s*mA.*?"
    r"V_BUS=(?P<vbus>[-\d.]+)\s*V.*?"
    r"BUS_OK=(?P<bus_ok>[01])"
)


# ============================================================
# 2. TÌM CỔNG SERIAL
# ============================================================

def find_port():

    candidates = []

    for p in serial.tools.list_ports.comports():

        if (
            p.device.startswith("/dev/cu.")
            and "Bluetooth" not in p.device
            and "debug-console" not in p.device
        ):
            candidates.append(p.device)

    if not candidates:

        for pat in (
            "/dev/cu.usbmodem*",
            "/dev/cu.usbserial*",
            "/dev/cu.wchusbserial*",
            "/dev/cu.SLAB_USBtoUART*"
        ):
            candidates += glob.glob(pat)

    for key in ("usbmodem", "usbserial", "wchusbserial", "SLAB"):

        for c in candidates:

            if key in c:
                return c

    return candidates[0] if candidates else None


# ============================================================
# 3. PHÂN TÍCH DỮ LIỆU UART
# ============================================================

def parse_line(line):

    m = LINE_RE.search(line)

    if not m:
        return None

    return {
        "vpa4": float(m["vpa4"]),
        "raw": int(m["raw"]),
        "vpa0": float(m["vpa0"]),
        "i_ma": float(m["i"]),
        "vbus": float(m["vbus"]),
        "bus_ok": int(m["bus_ok"]),
    }


# ============================================================
# 4. LƯU DỮ LIỆU CSV
# ============================================================

def save_csv(data):

    if not data:
        return

    name = datetime.now().strftime("iv_%Y%m%d_%H%M%S.csv")

    with open(name, "w", newline="") as f:

        w = csv.DictWriter(
            f,
            fieldnames=data[0].keys()
        )

        w.writeheader()
        w.writerows(data)

    print(f"Đã lưu: {name}")


# ============================================================
# 5. CHƯƠNG TRÌNH CHÍNH
# ============================================================

def main():

    # ---- Khởi tạo Tkinter để hiển thị popup ----

    root = tk.Tk()
    root.withdraw()

    # Cờ chống hiển thị popup liên tục
    bus_error_popup_shown = False

    ap = argparse.ArgumentParser()

    ap.add_argument(
        "-p",
        "--port",
        help="Cổng serial, mặc định tự tìm"
    )

    ap.add_argument(
        "-b",
        "--baud",
        type=int,
        default=115200
    )

    args = ap.parse_args()

    # ========================================================
    # 6. KHỞI TẠO ĐỒ THỊ
    # ========================================================

    plt.ion()

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=(12, 5)
    )

    (line1,) = ax1.plot(
        [],
        [],
        "o-",
        ms=4,
        color="tab:blue"
    )

    (line2,) = ax2.plot(
        [],
        [],
        "o",
        ms=4,
        color="tab:orange",
        alpha=0.7
    )

    ax1.set_xlabel("V_BUS (V)")
    ax1.set_ylabel("I (mA)")

    ax2.set_xlabel("V_PA0 (V)")
    ax2.set_ylabel("I (mA)")

    ax2.set_title("I-V theo V_PA0 (ADC)")

    for ax in (ax1, ax2):
        ax.grid(True, alpha=0.4)

    fig.tight_layout()

    # ========================================================
    # 7. HÀM CẬP NHẬT TRẠNG THÁI VÀ ĐỒ THỊ
    # ========================================================

    def set_status(status):

        ax1.set_title(
            f"Đặc tuyến I-V (V_BUS) - {status}"
        )

    def redraw(data):

        line1.set_data(
            [d["vbus"] for d in data],
            [d["i_ma"] for d in data]
        )

        line2.set_data(
            [d["vpa0"] for d in data],
            [d["i_ma"] for d in data]
        )

        for ax in (ax1, ax2):

            ax.relim()
            ax.autoscale_view()

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

    # ========================================================
    # 8. VÒNG LẶP CHÍNH
    # ========================================================

    data = []

    sweep_done = False

    ser = None

    set_status("đang chờ kết nối...")

    try:

        while plt.fignum_exists(fig.number):

            # ------------------------------------------------
            # 8.1 KẾT NỐI / KẾT NỐI LẠI SERIAL
            # ------------------------------------------------

            if ser is None:

                port = args.port or find_port()

                if not port:

                    set_status("không thấy cổng serial")

                    plt.pause(0.5)
                    continue

                try:

                    ser = serial.Serial(
                        port,
                        args.baud,
                        timeout=0.05
                    )

                    print(
                        f"Đã kết nối {port} @ {args.baud}"
                    )

                    set_status(
                        f"{port} - đang chờ dữ liệu "
                        "(nhấn RESET để bắt đầu)"
                    )

                except serial.SerialException as e:

                    print(f"Không mở được cổng: {e}")

                    ser = None

                    plt.pause(0.5)
                    continue

            # ------------------------------------------------
            # 8.2 ĐỌC DỮ LIỆU UART
            # ------------------------------------------------

            try:

                raw = ser.readline()

            except (serial.SerialException, OSError):

                print("Mất kết nối, đang thử lại...")

                try:
                    ser.close()
                except Exception:
                    pass

                ser = None

                set_status(
                    "mất kết nối, đang thử lại..."
                )

                plt.pause(0.5)
                continue

            if not raw:

                plt.pause(0.01)
                continue

            text = raw.decode(
                errors="ignore"
            ).strip()

            if not text:
                continue

            print(text)

            # ------------------------------------------------
            # 8.3 XỬ LÝ KẾT THÚC SWEEP
            # ------------------------------------------------

            if "SWEEP DONE" in text:

                sweep_done = True

                set_status(
                    f"sweep xong ({len(data)} điểm) "
                    "- nhấn RESET để đo lại"
                )

                if data:
                    save_csv(data)

                redraw(data)

                continue

            # ------------------------------------------------
            # 8.4 PHÂN TÍCH DỮ LIỆU
            # ------------------------------------------------

            row = parse_line(text)

            if not row:
                continue

            # ------------------------------------------------
            # 8.5 KIỂM TRA LỖI INA219 BUS
            # ------------------------------------------------

            if row["bus_ok"] == 0:

                print(
                    "[ERROR] INA219 BUS READ FAILED | "
                    f"V_PA4={row['vpa4']:.2f} V | "
                    f"BUS_OK={row['bus_ok']}"
                )

                # Chỉ hiển thị một popup trong một đợt lỗi
                if not bus_error_popup_shown:
                    bus_error_popup_shown = True

                    messagebox.showerror(
                        "INA219 Communication Error",
                        "Không thể đọc thanh ghi BUS Voltage!\n\n"
                        f"V_PA4: {row['vpa4']:.2f} V\n"
                        f"V_PA0: {row['vpa0']:.3f} V\n"
                        f"BUS_OK: {row['bus_ok']}\n\n"
                        "Vui lòng kiểm tra:\n"
                        "- Kết nối I2C (SCL/SDA)\n"
                        "- Nguồn cấp INA219\n"
                        "- Kết nối module cảm biến\n\n"
                        "Chương trình đã thoát.",
                        parent=root
                    )

                # Bỏ qua mẫu lỗi, KHÔNG thoát chương trình
                plt.close("all")
                continue

            else:

                # BUS đọc thành công trở lại
                bus_error_popup_shown = False

            # ------------------------------------------------
            # 8.6 PHÁT HIỆN SWEEP MỚI
            # ------------------------------------------------

            if (
                sweep_done
                or (
                    data
                    and row["vpa4"] < data[-1]["vpa4"]
                )
            ):

                data.clear()

                sweep_done = False

                print(
                    "--- Sweep mới, vẽ lại đồ thị ---"
                )

            # ------------------------------------------------
            # 8.7 CẬP NHẬT DỮ LIỆU VÀ ĐỒ THỊ
            # ------------------------------------------------

            data.append(row)

            set_status(
                f"đang sweep... "
                f"V_PA4 = {row['vpa4']:.2f} V"
            )

            redraw(data)

    finally:

        # ----------------------------------------------------
        # 8.8 GIẢI PHÓNG TÀI NGUYÊN
        # ----------------------------------------------------

        if ser is not None:

            try:
                ser.close()
            except Exception:
                pass

        root.destroy()


# ============================================================
# 9. ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\nĐã dừng chương trình.")
