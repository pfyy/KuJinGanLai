# -*- coding: utf-8 -*-
import os
import subprocess
import time
import threading
import tkinter
from tkinter import Tk
from tkinter import ttk


from win10toast import ToastNotifier

DEBUG = False

ADB = os.path.join(
    os.path.dirname(
        os.path.realpath(__file__)
    ), "platform-tools", "adb.exe"
)

if not os.path.isfile(ADB):
    print("warning, adb.exe not found, try to use adb.exe in system path")
    ADB = "adb.exe"


PACKAGE_NAMES = [
    "com.hypergryph.arknights",
    "com.hypergryph.arknights.bilibili"
]

MI = 1024**2

MAX_X86_VSS = 4096 * MI

EMU_MEM_THRESH = 300 * MI

X86_REM_VSS_THRESH = 300 * MI


TOAST = ToastNotifier()

# --- emulator functions ---


def show_toast(title: str, msg: str):
    TOAST.show_toast(title, msg, duration=10, threaded=True, icon_path='')


def find_emulators():
    proc = subprocess.run(
        [ADB, "devices"],
        capture_output=True,
        text=True
    )

    device_ids = []

    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if line:
            line_split = line.split()
            if line_split[-1] != "offline":
                device_ids.append(line_split[0])

    return device_ids


def find_emulator():
    device_ids = find_emulators()
    if device_ids:
        return device_ids[0]
    return None


def connect_to_emulator():
    device_ids = []

    # MUMU default

    # https://mumu.163.com/help/20220721/35047_730476.html
    # https://mumu.163.com/help/20230214/35047_1073151.html

    device_ids.append("127.0.0.1:16384")
    device_ids.append("127.0.0.1:7555")

    # LD default

    # https://help.ldmnq.com/docs/LD9adbserver

    device_ids.append("127.0.0.1:5555")

    # MUMU extra

    # https://mumu.163.com/help/20230214/35047_1073151.html

    MAX_NUM_MUMU = 4
    for i in range(1, MAX_NUM_MUMU):
        device_ids.append(f"127.0.0.1:{16384+32*i}")

    # LD extra

    # https://help.ldmnq.com/docs/LD9adbserver

    MAX_NUM_LD = 4
    for i in range(1, MAX_NUM_LD):
        device_ids.append(f"127.0.0.1:{5555+2*i}")

    # try connecting

    for device_id in device_ids:
        found_device_id = find_emulator()
        if found_device_id is not None:
            return found_device_id
        subprocess.run(
            [ADB, "connect", device_id]
        )

    found_device_id = find_emulator()
    if found_device_id is not None:
        return found_device_id


def is_emulator_alive(target_device_id):
    device_ids = find_emulators()
    return device_ids.count(target_device_id)


def get_package_abi(target_device_id):
    package_abi = {}
    for package_name in PACKAGE_NAMES:
        try:
            proc = subprocess.run(
                [
                    ADB, "-s", target_device_id, "shell",
                    "pm", "dump", package_name,
                    "|",
                    "grep", "primaryCpuAbi"
                ],
                capture_output=True,
                text=True
            )
            abi = proc.stdout.partition('primaryCpuAbi=')[-1].split()[0]
        except Exception:
            abi = None
        package_abi[package_name] = abi
    return package_abi


def get_app_mem(target_device_id):
    app_mem = {}
    for package_name in PACKAGE_NAMES:
        try:
            proc = subprocess.run(
                [
                    ADB, "-s", target_device_id, "shell",
                    "pidof", "-s", package_name
                ],
                capture_output=True,
                text=True
            )
            pid = int(proc.stdout)
            proc = subprocess.run(
                [
                    ADB, "-s", target_device_id, "shell", "cat",
                    f"/proc/{pid}/statm"
                ],
                capture_output=True,
                text=True
            )
            vss = int(proc.stdout.split()[0]) * 4096
        except Exception:
            vss = None
        app_mem[package_name] = vss
    return app_mem


def get_emulator_mem(target_device_id):
    try:
        proc = subprocess.run(
            [
                ADB, "-s", target_device_id, "shell", "free"
            ],
            capture_output=True,
            text=True
        )
        emulator_mem = int(proc.stdout.splitlines()[1].split()[3])
    except Exception:
        emulator_mem = None
    return emulator_mem


def do_check(target_device_id):
    status_text_arr = []
    try:
        package_abi = get_package_abi(target_device_id)
        app_mem = get_app_mem(target_device_id)
        emulator_mem = get_emulator_mem(target_device_id)

        msgs = []

        if emulator_mem is not None and (DEBUG or emulator_mem < EMU_MEM_THRESH):
            msgs.append(
                f"模拟器当前剩余物理内存为 {emulator_mem/MI:.0f} MiB"
            )

        if emulator_mem is not None:
            status_text_arr.append(
                f"剩余物理内存: {emulator_mem/MI:.0f} MiB"
            )

        for package_name in PACKAGE_NAMES:
            abi = package_abi[package_name]
            vss = app_mem[package_name]

            if vss is not None:
                x86_remaining_vss = MAX_X86_VSS - vss

            if abi == "x86":
                status_text_arr.append(
                    f"警告: {package_name}正在使用32位x86架构, 最大虚拟内存为4GiB"
                )

            if (
                abi == "x86" and vss is not None and
                (DEBUG or x86_remaining_vss < X86_REM_VSS_THRESH)
            ):
                msgs.append(
                    f"游戏进程当前剩余虚拟内存为 {x86_remaining_vss/MI:.0f} MiB"
                )

            if abi == "x86" and vss is not None:
                status_text_arr.append(
                    f"{package_name} 剩余虚拟内存: {x86_remaining_vss/MI:.0f} MiB"
                )
        if msgs:
            msg = '; '.join(msgs)
            show_toast("⚠⚠⚠ 滴嘟滴嘟 ⚠⚠⚠", msg)
    except Exception:
        pass
    return status_text_arr


# --- threads ---

running = True

current_device_id = None


def update_device_id_thread_func():
    global running
    global current_device_id

    cnt = 0
    while running:
        if not cnt:
            if DEBUG:
                print("update_device_id_thread_func called")
            if current_device_id is not None:
                if not is_emulator_alive(current_device_id):
                    current_device_id = None

            if current_device_id is None:
                current_device_id = connect_to_emulator()
        cnt += 1
        # 3s
        if cnt >= 30:
            cnt = 0
        time.sleep(0.1)


update_device_id_thread = threading.Thread(target=update_device_id_thread_func)
update_device_id_thread.start()

label_text = None


def do_check_thread_func():
    global running
    global current_device_id
    global label_text

    cnt = 0
    while running:
        if not cnt:
            if DEBUG:
                print("do_check_thread_func called")
            if current_device_id is not None:
                device_id = current_device_id
                status_text_arr = do_check(device_id)
                if not status_text_arr:
                    status_text_arr = [f"模拟器{device_id}未给出有效响应"]
                status_text_arr = [
                    f"当前模拟器: {device_id}",
                    "----------------------------------------"
                ] + status_text_arr + [
                    "----------------------------------------"
                ]
                status_text = '\n'.join(status_text_arr)
            else:
                status_text = "正在寻找运行中的模拟器..."
            if label_text is not None:
                label_text.set(status_text)
        cnt += 1
        # 1s
        if cnt >= 10:
            cnt = 0
        time.sleep(0.1)


do_check_thread = threading.Thread(target=do_check_thread_func)
do_check_thread.start()

# --- tkinter ---


root = Tk()
root.rowconfigure(0, weight=1)
root.columnconfigure(0, weight=1)

frm = ttk.Frame(root, padding=100)
frm.grid(sticky=tkinter.NSEW)

label_text = tkinter.StringVar(value="启动中...")
label = ttk.Label(frm, textvariable=label_text, anchor=tkinter.CENTER).grid(
    column=0, row=0, sticky=tkinter.NSEW)


for i in range(1):
    frm.rowconfigure(i, weight=1)

for i in range(1):
    frm.columnconfigure(i, weight=1)

try:
    root.mainloop()
except KeyboardInterrupt:
    pass

label_text = None

running = False

update_device_id_thread.join()

do_check_thread.join()
