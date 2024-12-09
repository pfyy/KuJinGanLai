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


PACKAGE_NAMES = [
    "com.hypergryph.arknights",
    "com.hypergryph.arknights.bilibili"
]

TOAST = ToastNotifier()

# --- emulator functions ---


def show_toast(title: str, msg: str):
    TOAST.show_toast(title, msg, duration=10, threaded=True)


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
    status_text = ""
    try:
        package_abi = get_package_abi(target_device_id)
        app_mem = get_app_mem(target_device_id)
        emulator_mem = get_emulator_mem(target_device_id)

        msgs = []

        MI = 1024**2
        if emulator_mem is not None and (DEBUG or emulator_mem < 300*MI):
            msgs.append(
                f"模拟器当前剩余物理内存为 {emulator_mem/MI:.0f} MiB"
            )

        if emulator_mem is not None:
            status_text += f"剩余物理内存: {emulator_mem/MI:.0f} MiB\n"

        for package_name in PACKAGE_NAMES:
            abi = package_abi[package_name]
            vss = app_mem[package_name]

            MAX_X86_VSS = 4096 * MI

            if (
                abi == "x86" and vss is not None and
                (DEBUG or MAX_X86_VSS - vss < 300*MI)
            ):
                msgs.append(
                    f"游戏进程当前剩余虚拟内存为 {(MAX_X86_VSS - vss)/MI:.0f} MiB"
                )

            if abi == "x86" and vss is not None:
                status_text += f"{package_name} 剩余虚拟内存: {
                    (MAX_X86_VSS - vss)/MI:.0f
                } MiB\n"
        if msgs:
            msg = '; '.join(msgs)
            show_toast("⚠⚠⚠ 滴嘟滴嘟 ⚠⚠⚠", msg)
    except Exception:
        pass
    return status_text


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
        # 30s
        if cnt >= 300:
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
                status_text = do_check(device_id)
                if label_text is not None:
                    label_text.set(status_text)
        cnt += 1
        # 5s
        if cnt >= 50:
            cnt = 0
        time.sleep(0.1)


do_check_thread = threading.Thread(target=do_check_thread_func)
do_check_thread.start()

# --- tkinter ---


root = Tk()
frm = ttk.Frame(root, padding=50)
frm.grid()
label_text = tkinter.StringVar(value="启动中...")
label = ttk.Label(frm, textvariable=label_text).grid(column=0, row=0)


def exit_func():
    global running
    running = False

    global update_device_id_thread
    update_device_id_thread.join()

    global do_check_thread
    do_check_thread.join()

    global root
    root.destroy()


ttk.Button(frm, text="Quit", command=exit_func).grid(column=0, row=1)


root.mainloop()
