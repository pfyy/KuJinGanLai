# -*- coding: utf-8 -*-
import os
import subprocess
import time
import threading
import sys
import json
import tkinter
from tkinter import Tk
from tkinter import ttk


from win10toast import ToastNotifier
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from playsound3 import playsound


# for chinese user
plt.rcParams["font.family"] = "SimSun"
plt.rcParams["axes.unicode_minus"] = False

DEBUG = False

EXTENDED_DEVICE_SCAN = False

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    SELF_DIR_PATH = os.path.dirname(sys.executable)
else:
    SELF_DIR_PATH = os.path.dirname(
        os.path.realpath(__file__)
    )


ADB = os.path.join(
    SELF_DIR_PATH, "platform-tools", "adb.exe"
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

T_START = time.time()

T_SOUND_PERIOD = 15


SETTING_FILE_PATH = os.path.join(
    SELF_DIR_PATH, "settings.json"
)

SOUND_FILE_PATH = os.path.join(
    SELF_DIR_PATH, "proprietary_asset", "kujinganlai.mp3"
)


class Setting:
    def __init__(self):
        if os.path.isfile(SETTING_FILE_PATH):
            with open(SETTING_FILE_PATH, encoding="utf-8") as f:
                self.setting_obj = json.load(f)
        else:
            self.setting_obj = {
                "use_audio": 0,
            }

    def get_key(self, k):
        return self.setting_obj.get(k, None)

    def set_key(self, k, v):
        self.setting_obj[k] = v
        with open(SETTING_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                self.setting_obj, f,
                ensure_ascii=False, indent=4
            )


setting = Setting()

# --- emulator functions ---

last_playsound_time = 0


def do_message_warn(title: str, msg: str):
    if DEBUG:
        print("do_message_warn called")
    TOAST.show_toast(title, msg, duration=10, threaded=True, icon_path='')


def do_audio_warn():
    if DEBUG:
        print("do_audio_warn called")
    playsound(SOUND_FILE_PATH, block=False)


warn_disabled = False


def do_warn(title: str, msg: str, ignore_sound_period: bool = False):
    global warn_disabled
    if warn_disabled:
        return
    do_message_warn(title, msg)
    if setting.get_key("use_audio"):
        global last_playsound_time

        t_now = time.time()
        if ignore_sound_period or t_now > last_playsound_time+T_SOUND_PERIOD:
            last_playsound_time = t_now
            do_audio_warn()


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

    if EXTENDED_DEVICE_SCAN:

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


class GraphOrigData:
    LEN_GRAPH_DATA = 10000

    def __init__(self):
        self.x_arr = []
        self.y_arr = []
        self.lock = threading.Lock()

    def add(self, new_x, new_y):
        with self.lock:
            self.x_arr.append(new_x)
            self.y_arr.append(new_y)

    def get_graph_data(self):
        with self.lock:
            return (
                self.x_arr[-self.LEN_GRAPH_DATA:],
                self.y_arr[-self.LEN_GRAPH_DATA:]
            )


graph_orig_data_dict = {}

graph_orig_data_dict["emulator_mem"] = GraphOrigData()

for package_name in PACKAGE_NAMES:
    graph_orig_data_dict[
        f"x86_remaining_vss-{package_name}"
    ] = GraphOrigData()


def do_check(target_device_id):
    global graph_orig_data_dict

    status_text_arr = []
    try:
        package_abi = get_package_abi(target_device_id)
        app_mem = get_app_mem(target_device_id)
        emulator_mem = get_emulator_mem(target_device_id)

        t_now = time.time()

        msgs = []

        if emulator_mem is not None and (
            DEBUG or emulator_mem < EMU_MEM_THRESH
        ):
            msgs.append(
                f"模拟器当前剩余物理内存为 {emulator_mem/MI:.0f} MiB"
            )

        if emulator_mem is not None:
            status_text_arr.append(
                f"剩余物理内存: {emulator_mem/MI:.0f} MiB"
            )

        if emulator_mem is not None:
            graph_orig_data_dict["emulator_mem"].add(
                t_now-T_START, emulator_mem/MI
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

            if abi == "x86" and vss is not None:
                graph_orig_data_dict[
                    f"x86_remaining_vss-{package_name}"
                ].add(
                    t_now-T_START, x86_remaining_vss/MI
                )
        if msgs:
            msg = '; '.join(msgs)
            do_warn("⚠⚠⚠ 滴嘟滴嘟 ⚠⚠⚠", msg)
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


# --- threads with gui interaction ---


# tkinter root, may be none when thread starts
root = None

status_text = ''


def do_check_thread_func():
    global running
    global current_device_id

    global status_text

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
            if root is not None:
                root.event_generate("<<label_updated>>")
        cnt += 1
        # 1s
        if cnt >= 10:
            cnt = 0
        time.sleep(0.1)


do_check_thread = threading.Thread(target=do_check_thread_func)
do_check_thread.start()


fig = Figure()
ax = fig.add_subplot()
ax2 = ax.twinx()


def draw_graph_thread_func():
    global running

    global graph_orig_data_dict

    global ax
    global ax2
    global root

    while running:
        if ax is not None and ax2 is not None:
            ax.clear()
            ax2.clear()

            ax.set_xlabel("时间 (s)")
            ax.set_ylabel("内存大小 (MiB)")

            emulator_mem_x, emulator_mem_y = graph_orig_data_dict[
                "emulator_mem"
            ].get_graph_data()

            if emulator_mem_x:
                ax.plot(
                    emulator_mem_x, emulator_mem_y,
                    color="black", label="模拟器剩余物理内存"
                )

                ax.set_ylim(bottom=0, top=1.2*max(emulator_mem_y))

            app_x86_remaining_vss = {}

            for package_name in PACKAGE_NAMES:
                app_x86_remaining_vss[package_name] = graph_orig_data_dict[
                    f"x86_remaining_vss-{package_name}"
                ].get_graph_data()

            x86_remaining_vss_y_max = 0

            for package_name in PACKAGE_NAMES:
                (
                    x86_remaining_vss_x,
                    x86_remaining_vss_y
                ) = app_x86_remaining_vss[
                    package_name
                ]
                if x86_remaining_vss_x:
                    ax2.plot(
                        x86_remaining_vss_x,
                        x86_remaining_vss_y,
                        label="明日方舟剩余虚拟内存"
                    )
                    x86_remaining_vss_y_max = max(
                        x86_remaining_vss_y_max,
                        max(x86_remaining_vss_y)
                    )

            ax2.set_ylim(bottom=0, top=1.2*x86_remaining_vss_y_max)

            ax.legend(
                loc="upper left"
            )
            ax2.legend(
                loc="upper right"
            )

            if root is not None:
                root.event_generate("<<canvas_updated>>")

        time.sleep(0.5)


draw_graph_thread = threading.Thread(target=draw_graph_thread_func)
draw_graph_thread.start()

# --- tkinter ---


root = Tk()
root.rowconfigure(0, weight=1)
root.columnconfigure(0, weight=1)

frm = ttk.Frame(root, padding=10)
frm.grid(sticky=tkinter.NSEW)

label_text = tkinter.StringVar(value="启动中...")
label = ttk.Label(frm, textvariable=label_text, anchor=tkinter.CENTER).grid(
    column=0, row=0, sticky=tkinter.NSEW)


canvas = FigureCanvasTkAgg(fig, master=frm)
canvas.get_tk_widget().grid(column=0, row=1)

check_button_val = tkinter.IntVar(value=setting.get_key("use_audio"))
check_button = tkinter.Checkbutton(
    frm,
    text="开启苦尽甘来语音提醒",
    variable=check_button_val,
    command=lambda: setting.set_key("use_audio", check_button_val.get())
)
check_button.grid(column=0, row=2)

test_button = tkinter.Button(
    frm, text="测试提醒功能",
    command=lambda: do_warn("测试标题", "测试内容", ignore_sound_period=True)
)
test_button.grid(column=0, row=3)


mask_button_val = tkinter.IntVar(value=0)


def mask_button_cmd():
    global warn_disabled

    global mask_button_val

    warn_disabled = mask_button_val.get()


mask_button = tkinter.Checkbutton(
    frm,
    text="屏蔽苦尽甘来警告",
    variable=mask_button_val,
    command=mask_button_cmd
)
mask_button.grid(column=0, row=4)


for i in range(5):
    frm.rowconfigure(i, weight=1)

for i in range(1):
    frm.columnconfigure(i, weight=1)


root.bind("<<label_updated>>", lambda e: label_text.set(status_text))
root.bind("<<canvas_updated>>", lambda e: canvas.draw_idle())

try:
    root.mainloop()
except KeyboardInterrupt:
    pass

running = False

update_device_id_thread.join()

do_check_thread.join()

draw_graph_thread.join()
