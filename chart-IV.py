#!/usr/bin/env python3
"""
Vẽ đặc tuyến I-V realtime từ UART (macOS).

Chức năng:
- Nhấn nút RESET trên board -> sweep mới -> đồ thị tự xóa và vẽ lại.
- Tự kết nối lại nếu cổng Serial bị mất.
- Mỗi lần sweep xong ("SWEEP DONE") tự lưu CSV và ảnh PNG (cùng tên).
- Nếu INA219 BUS_OK = 0: hiện hộp thoại macOS gốc (chạy ở tiến trình riêng,
  không dùng matplotlib, không dùng Tkinter, không chặn đồ thị).
- Bấm Close trên hộp thoại chỉ đóng hộp thoại đó, đồ thị vẫn chạy.
- Chỉ hiển thị một hộp thoại cho mỗi đợt lỗi liên tục.
- Ctrl+C / nút Stop của PyCharm sẽ thoát êm.

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
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
import matplotlib.pyplot as plt
import serial
import serial.tools.list_ports


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

    result_dir = "results"
    os.makedirs(result_dir, exist_ok=True)

    base = datetime.now().strftime("iv_%Y%m%d_%H%M%S")
    name = os.path.join(result_dir, f"{base}.csv")

    with open(name, "w", newline="", encoding="utf-8-sig") as f:

        w = csv.DictWriter(
            f,
            fieldnames=data[0].keys()
        )

        w.writeheader()
        w.writerows(data)

    print(f"Đã lưu CSV: {name}")

    return base

def save_png(fig, base):
    """Lưu ảnh đồ thị hiện tại vào folder result."""
    result_dir = "results"
    os.makedirs(result_dir, exist_ok=True)

    name = os.path.join(result_dir, f"{base}.png")

    try:
        fig.canvas.draw()
        fig.savefig(name, dpi=150, bbox_inches="tight")
        print(f"Đã lưu ảnh: {name}")
    except Exception as e:
        print(f"Không lưu được ảnh: {e}")


# ============================================================
# 5. HỘP THOẠI LỖI (TIẾN TRÌNH RIÊNG, KHÔNG CHẶN CHƯƠNG TRÌNH)
# ============================================================

def show_bus_error_dialog(row):
    """
    Hiện hộp thoại macOS gốc bằng osascript, chạy ở tiến trình riêng.
    Trả về đối tượng Popen (hoặc None nếu không phải macOS / lỗi).
    Bấm Close chỉ đóng hộp thoại, không ảnh hưởng đồ thị.
    """

    if sys.platform != "darwin":
        return None

    msg = (
        "Không thể đọc thanh ghi BUS Voltage!\n\n"
        f"V_PA4: {row['vpa4']:.2f} V\n"
        f"V_PA0: {row['vpa0']:.3f} V\n"
        f"BUS_OK: {row['bus_ok']}\n\n"
        "Vui lòng kiểm tra:\n"
        "- Kết nối I2C (SCL/SDA)\n"
        "- Nguồn cấp INA219\n"
        "- Kết nối module cảm biến"
    )

    title = "INA219 Communication Error"

    try:
        return subprocess.Popen(
            [
                "osascript",
                "-e", "on run argv",
                "-e", (
                    "display dialog (item 1 of argv) "
                    "with title (item 2 of argv) "
                    'buttons {"Close"} default button "Close" '
                    "with icon stop"
                ),
                "-e", "end run",
                msg,
                title,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(f"Không mở được hộp thoại lỗi: {e}")
        return None


def close_dialog(proc):
    """Đóng hộp thoại nếu còn mở."""

    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


# ============================================================
# 6. CHƯƠNG TRÌNH CHÍNH
# ============================================================

def main():

    # ---- Bắt Ctrl+C / Stop để thoát êm ----

    stop = {"flag": False}

    signal.signal(
        signal.SIGINT,
        lambda *_: stop.__setitem__("flag", True)
    )

    # Cờ chống mở hộp thoại liên tục + tiến trình hộp thoại
    bus_error_popup_shown = False
    error_proc = None

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
    # 7. KHỞI TẠO ĐỒ THỊ
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
    # 8. HÀM CẬP NHẬT TRẠNG THÁI VÀ ĐỒ THỊ
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
    # 9. VÒNG LẶP CHÍNH
    # ========================================================

    data = []

    sweep_done = False

    ser = None

    set_status("đang chờ kết nối...")

    try:

        while plt.fignum_exists(fig.number) and not stop["flag"]:

            # ------------------------------------------------
            # 9.1 KẾT NỐI / KẾT NỐI LẠI SERIAL
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
            # 9.2 ĐỌC DỮ LIỆU UART
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
            # 9.2.1 XỬ LÝ INA219 DETECTED -- VẼ LẠI CHART
            # ------------------------------------------------
            if "INA219 DETECTED" in text:

                print("[INFO] INA219 đã được nhận diện - Reset chart")

                # Xóa dữ liệu sweep cũ
                data.clear()

                # Reset trạng thái sweep
                sweep_done = False

                # Reset trạng thái cảnh báo lỗi INA219
                bus_error_popup_shown = False

                # Đóng hộp thoại lỗi nếu đang mở
                close_dialog(error_proc)
                error_proc = None

                # Xóa dữ liệu trên cả hai đồ thị
                line1.set_data([], [])
                line2.set_data([], [])

                # Reset giới hạn trục tọa độ
                for ax in (ax1, ax2):
                    ax.relim()
                    ax.autoscale_view()

                # Cập nhật tiêu đề
                set_status("INA219 DETECTED - sẵn sàng đo")

                # Cập nhật giao diện ngay lập tức
                fig.canvas.draw()
                fig.canvas.flush_events()

                continue
            # ------------------------------------------------
            # 9.3b MỖI LẦN BẤM NÚT: SWEEP START / ABORTED / STOPPED
            # ------------------------------------------------

            if "SWEEP START" in text:

                # Lần bấm mới: xóa đồ thị, cho phép hiện hộp thoại lỗi mới
                data.clear()
                sweep_done = False
                bus_error_popup_shown = False

                close_dialog(error_proc)
                error_proc = None

                set_status("bắt đầu sweep...")
                redraw(data)

                continue

            if "SWEEP ABORTED" in text:

                set_status(
                    "sweep bị hủy do lỗi INA219 "
                    "- bấm nút để thử lại"
                )

                redraw(data)

                continue

            if "SWEEP STOPPED" in text:

                set_status(
                    f"đã dừng thủ công ({len(data)} điểm) "
                    "- bấm nút để đo lại"
                )

                continue
            if "SWEEP PAUSED" in text:
                set_status("TẠM DỪNG - nhấn USER BUTTON để tiếp tục")
                continue

            if "SWEEP CONTINUED" in text:
                set_status("đang tiếp tục sweep...")
                continue
            # ------------------------------------------------
            # 9.3 XỬ LÝ KẾT THÚC SWEEP
            # ------------------------------------------------

            if "SWEEP DONE" in text:

                sweep_done = True

                set_status(
                    f"sweep xong ({len(data)} điểm) "
                    "- nhấn RESET để đo lại"
                )

                # Vẽ lại trước để ảnh có đủ dữ liệu và tiêu đề trạng thái
                redraw(data)

                if data:
                    base = save_csv(data)
                    save_png(fig, base)

                continue

            # ------------------------------------------------
            # 9.4 PHÂN TÍCH DỮ LIỆU
            # ------------------------------------------------

            row = parse_line(text)

            if not row:
                continue

            # ------------------------------------------------
            # 9.5 KIỂM TRA LỖI INA219 BUS
            # ------------------------------------------------

            if row["bus_ok"] == 0:

                print(
                    "[ERROR] INA219 BUS READ FAILED | "
                    f"V_PA4={row['vpa4']:.2f} V | "
                    f"BUS_OK={row['bus_ok']}"
                )

                # Chỉ mở một hộp thoại cho mỗi đợt lỗi liên tục
                if not bus_error_popup_shown:
                    bus_error_popup_shown = True
                    error_proc = show_bus_error_dialog(row)

                # Bỏ qua mẫu lỗi, đồ thị vẫn chạy bình thường
                continue

            else:

                # BUS đọc thành công trở lại
                bus_error_popup_shown = False

                # Tự đóng hộp thoại lỗi nếu còn mở
                close_dialog(error_proc)
                error_proc = None

            # ------------------------------------------------
            # 9.6 PHÁT HIỆN SWEEP MỚI
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
            # 9.7 CẬP NHẬT DỮ LIỆU VÀ ĐỒ THỊ
            # ------------------------------------------------

            data.append(row)

            set_status(
                f"đang sweep... "
                f"V_PA4 = {row['vpa4']:.2f} V"
            )

            redraw(data)

    finally:

        # ----------------------------------------------------
        # 9.8 GIẢI PHÓNG TÀI NGUYÊN
        # ----------------------------------------------------

        close_dialog(error_proc)

        if ser is not None:

            try:
                ser.close()
            except Exception:
                pass

        try:
            plt.close("all")
        except Exception:
            pass


# ============================================================
# 10. ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\nĐã dừng chương trình.")