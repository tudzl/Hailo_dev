#!/usr/bin/env python3
"""
Hailo8 测试 GUI（运行于树莓派5桌面）

用途：为 ~/tutorial/Hailo_apps/hailo-apps-main 下的 Hailo 示例应用提供一个
图形化入口，点击按钮即在新终端窗口中 cd 到项目目录、激活 venv、执行对应命令，
方便做各类 Hailo8 用例的手动测试（目标检测/姿态/人脸识别/深度/分割等），
同时提供自定义命令执行、状态监控 App 启动、一键停止等辅助功能。

部署方法：
    1. 把本文件拷贝到树莓派（例如 ~/tutorial/hailo_test_gui.py）
    2. 确认已安装 tkinter： sudo apt install -y python3-tk
    3. 在树莓派桌面（本地屏幕或VNC，需要有 DISPLAY，不能是纯SSH无图形会话）运行：
           python3 ~/tutorial/hailo_test_gui.py
    4. 首次使用请在顶部"项目目录"确认路径是否正确（默认已填好）
"""

import os
import shlex
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

HOME = os.path.expanduser("~")
DEFAULT_PROJECT_DIR = os.path.join(HOME, "tutorial", "Hailo_apps", "hailo-apps-main")
DEFAULT_SETUP_SCRIPT = "setup_env.sh"
DEFAULT_MONITOR_APP = os.path.join(HOME, "Docker", "Python_APP", "hailo_monitor_v3B.py")

# 终端模拟器检测优先级：Raspberry Pi OS 默认是 lxterminal
TERMINAL_CANDIDATES = ["lxterminal", "xterm", "gnome-terminal", "konsole", "mate-terminal", "xfce4-terminal"]

# 预置的 Hailo 示例命令：(显示名称, 可执行文件, 默认附加参数)
EXAMPLE_APPS = [
    ("目标检测 - Simple (YOLOv5m)", "hailo-detect-simple", "--input rpi --hef-path yolov5m_wo_spp --show-fps"),
    ("目标检测 - 标准版", "hailo-detect", "--input rpi --show-fps"),
    ("姿态估计 (Pose)", "hailo-pose", "--input rpi --show-fps"),
    ("人脸识别 (Face Recognition)", "hailo-face-recon", "--input rpi --show-fps"),
    ("深度估计 (Depth)", "hailo-depth", "--input rpi --show-fps"),
    ("图像分割 (Segmentation)", "hailo-seg", "--input rpi --show-fps"),
    ("OCR 文字识别", "hailo-ocr", "--input rpi --show-fps"),
    ("ReID 行人重识别", "hailo-reid", "--input rpi --show-fps"),
    ("CLIP", "hailo-clip", "--input rpi --show-fps"),
    ("多路输入 (Multisource)", "hailo-multisource", "--show-fps"),
    ("Tiling", "hailo-tiling", "--input rpi --show-fps"),
    ("音频故障排查", "hailo-audio-troubleshoot", ""),
    ("下载模型资源", "hailo-download-resources", ""),
    ("编译后处理", "hailo-compile-postprocess", ""),
    ("安装后设置 (post-install)", "hailo-post-install", ""),
    ("环境设置 (set-env)", "hailo-set-env", ""),
]


def find_terminal():
    for name in TERMINAL_CANDIDATES:
        path = shutil.which(name)
        if path:
            return name
    return None


def build_terminal_argv(term, inner_bash_cmd):
    """按不同终端模拟器的调用语法，构造用于 subprocess.Popen 的 argv 列表。"""
    if term == "lxterminal":
        return ["lxterminal", "-e", "bash", "-c", inner_bash_cmd]
    if term == "xterm":
        return ["xterm", "-hold", "-e", "bash", "-c", inner_bash_cmd]
    if term == "gnome-terminal":
        return ["gnome-terminal", "--", "bash", "-c", inner_bash_cmd]
    if term == "konsole":
        return ["konsole", "-e", "bash", "-c", inner_bash_cmd]
    if term == "mate-terminal":
        return ["mate-terminal", "-e", "bash -c {}".format(shlex.quote(inner_bash_cmd))]
    if term == "xfce4-terminal":
        return ["xfce4-terminal", "-e", "bash -c {}".format(shlex.quote(inner_bash_cmd))]
    # 兜底：直接用 bash 执行（不开新窗口）
    return ["bash", "-c", inner_bash_cmd]


class HailoTestGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hailo8 测试 GUI - Raspberry Pi 5")
        self.geometry("980x720")

        self.term_name = find_terminal()
        self.launched_procs = []  # 记录已启动的终端子进程，便于“停止全部”时兜底kill

        self._build_top_frame()
        self._build_examples_frame()
        self._build_custom_frame()
        self._build_tools_frame()
        self._build_log_frame()

        self._log("GUI 已启动。")
        if self.term_name:
            self._log(f"检测到终端模拟器: {self.term_name}")
        else:
            self._log("警告：未检测到可用的终端模拟器 (lxterminal/xterm/gnome-terminal...)，"
                       "命令将尝试直接后台执行，无法看到实时输出/摄像头预览窗口可能无法正常弹出。")

    # ---------- 顶部：项目目录与环境 ----------
    def _build_top_frame(self):
        frame = ttk.LabelFrame(self, text="项目环境")
        frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(frame, text="项目目录:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.project_dir_var = tk.StringVar(value=DEFAULT_PROJECT_DIR)
        ttk.Entry(frame, textvariable=self.project_dir_var, width=60).grid(row=0, column=1, sticky="we", padx=4)

        ttk.Label(frame, text="环境脚本:").grid(row=0, column=2, sticky="w", padx=4)
        self.setup_script_var = tk.StringVar(value=DEFAULT_SETUP_SCRIPT)
        ttk.Entry(frame, textvariable=self.setup_script_var, width=20).grid(row=0, column=3, sticky="we", padx=4)

        ttk.Button(frame, text="打开项目目录终端", command=self.open_project_terminal).grid(
            row=0, column=4, padx=6)

        self.hailo_monitor_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text="运行 App 前先 export HAILO_MONITOR=1（配合 hailortcli monitor 性能监控）",
            variable=self.hailo_monitor_var
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 4))

        ttk.Button(frame, text="打开性能监控终端 (hailortcli monitor)",
                   command=self.open_monitor_terminal).grid(row=1, column=4, padx=6, pady=(0, 4))

        frame.columnconfigure(1, weight=1)

    # ---------- Hailo 示例按钮区 ----------
    def _build_examples_frame(self):
        outer = ttk.LabelFrame(self, text="Hailo 示例 Apps（点击“运行”会在新终端窗口中执行，可按住 Ctrl+C / 关闭窗口 停止）")
        outer.pack(fill="both", expand=False, padx=10, pady=6)

        canvas = tk.Canvas(outer, height=330)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.args_vars = {}
        for row, (label, exe, default_args) in enumerate(EXAMPLE_APPS):
            ttk.Label(inner, text=label, width=28).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            ttk.Label(inner, text=exe, width=24, foreground="#555").grid(row=row, column=1, sticky="w", padx=4)
            var = tk.StringVar(value=default_args)
            self.args_vars[exe] = var
            ttk.Entry(inner, textvariable=var, width=36).grid(row=row, column=2, sticky="we", padx=4)
            ttk.Button(inner, text="运行", width=8,
                       command=lambda e=exe, v=var: self.run_app(e, v.get())).grid(
                row=row, column=3, padx=6)

        inner.columnconfigure(2, weight=1)

    # ---------- 自定义命令 ----------
    def _build_custom_frame(self):
        frame = ttk.LabelFrame(
            self, text="自定义命令（多行，支持粘贴整段脚本；会自动 cd 项目目录并 source 环境脚本后再执行）")
        frame.pack(fill="x", padx=10, pady=6)

        self.custom_cmd_text = tk.Text(frame, height=4, width=90, wrap="none")
        self.custom_cmd_text.insert(
            "1.0", 'find hailo_apps/python -maxdepth 3 -name "*.py" | head -40')
        self.custom_cmd_text.grid(row=0, column=0, columnspan=3, sticky="we", padx=6, pady=6)

        cmd_scroll = ttk.Scrollbar(frame, orient="vertical", command=self.custom_cmd_text.yview)
        cmd_scroll.grid(row=0, column=3, sticky="ns")
        self.custom_cmd_text.configure(yscrollcommand=cmd_scroll.set)

        ttk.Button(frame, text="一键执行（新终端窗口）", command=self.run_custom_in_terminal).grid(
            row=1, column=0, padx=6, pady=(0, 6), sticky="we")
        ttk.Button(frame, text="一键执行（本窗口显示输出）", command=self.run_custom_inline).grid(
            row=1, column=1, padx=6, pady=(0, 6), sticky="we")
        ttk.Button(frame, text="清空", command=self._clear_custom_cmd).grid(
            row=1, column=2, padx=6, pady=(0, 6))

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _clear_custom_cmd(self):
        self.custom_cmd_text.delete("1.0", "end")

    def _get_custom_cmd(self):
        return self.custom_cmd_text.get("1.0", "end").strip()

    # ---------- 辅助工具 ----------
    def _build_tools_frame(self):
        frame = ttk.LabelFrame(self, text="辅助工具")
        frame.pack(fill="x", padx=10, pady=6)

        ttk.Button(frame, text="启动 Hailo 状态监控 APP", command=self.run_monitor_app).grid(
            row=0, column=0, padx=6, pady=6)
        ttk.Button(frame, text="列出可用 hailo- 命令", command=self.list_hailo_bins).grid(
            row=0, column=1, padx=6)
        ttk.Button(frame, text="停止所有 Hailo 进程", command=self.stop_all_hailo).grid(
            row=0, column=2, padx=6)

    # ---------- 日志输出区 ----------
    def _build_log_frame(self):
        frame = ttk.LabelFrame(self, text="日志 / 输出")
        frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.log_text = scrolledtext.ScrolledText(frame, height=14, state="normal")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _log(self, text):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    # ---------- 命令构造 ----------
    def _env_prefix(self):
        proj_dir = self.project_dir_var.get().strip()
        setup_script = self.setup_script_var.get().strip()
        return f"cd {shlex.quote(proj_dir)} && source {shlex.quote(setup_script)}"

    def _launch_in_terminal(self, user_cmd, keep_open=True):
        prefix = self._env_prefix()
        if keep_open:
            inner = f"{prefix} && {user_cmd}; echo; echo '[命令已结束，按 Enter 关闭此窗口]'; read"
        else:
            inner = f"{prefix} && {user_cmd}"

        if self.term_name:
            argv = build_terminal_argv(self.term_name, inner)
        else:
            argv = ["bash", "-c", inner]

        self._log(f"$ {user_cmd}")
        try:
            proc = subprocess.Popen(argv)
            self.launched_procs.append(proc)
        except Exception as e:
            messagebox.showerror("启动失败", f"无法启动命令：\n{user_cmd}\n\n错误：{e}")
            self._log(f"错误: {e}")

    def run_app(self, exe, args):
        cmd = f"{exe} {args}".strip()
        self._launch_in_terminal(cmd)

    def open_project_terminal(self):
        prefix = self._env_prefix()
        inner = f"{prefix}; exec bash"
        if self.term_name:
            argv = build_terminal_argv(self.term_name, inner)
        else:
            messagebox.showwarning("提示", "未检测到终端模拟器，无法打开交互终端窗口。")
            return
        self._log("打开项目目录终端...")
        try:
            proc = subprocess.Popen(argv)
            self.launched_procs.append(proc)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    def run_custom_in_terminal(self):
        cmd = self._get_custom_cmd()
        if not cmd:
            return
        self._launch_in_terminal(cmd)

    def run_custom_inline(self):
        cmd = self._get_custom_cmd()
        if not cmd:
            return
        prefix = self._env_prefix()
        full = f"{prefix} && {cmd}"
        self._log(f"$ {cmd}  (本窗口同步执行，输出见下)")
        try:
            result = subprocess.run(
                ["bash", "-c", full],
                capture_output=True, text=True, timeout=120
            )
            if result.stdout:
                self._log(result.stdout.rstrip())
            if result.stderr:
                self._log("[stderr] " + result.stderr.rstrip())
            self._log(f"[退出码: {result.returncode}]")
        except subprocess.TimeoutExpired:
            self._log("[超时：命令运行超过120秒，建议改用“在新终端运行”，"
                       "尤其是带摄像头预览的持续运行类命令]")
        except Exception as e:
            self._log(f"[错误] {e}")

    def run_monitor_app(self):
        monitor_path = DEFAULT_MONITOR_APP
        if not os.path.exists(monitor_path):
            messagebox.showwarning(
                "找不到文件",
                f"未找到监控 APP：\n{monitor_path}\n请确认路径是否正确。"
            )
            return
        cmd = f"python3 {shlex.quote(monitor_path)}"
        self._launch_in_terminal(cmd)

    def list_hailo_bins(self):
        prefix = self._env_prefix()
        cmd = f'{prefix} && ls "$(dirname "$(which hailo-detect-simple)")"/hailo-*'
        self._log("$ 列出可用 hailo- 命令")
        try:
            result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
            out = result.stdout.strip() or result.stderr.strip()
            self._log(out)
        except Exception as e:
            self._log(f"[错误] {e}")

    def stop_all_hailo(self):
        if not messagebox.askyesno("确认", "将尝试结束所有正在运行的 hailo- 相关进程，确认继续？"):
            return
        patterns = ["hailo-detect", "hailo-pose", "hailo-face-recon", "hailo-depth",
                    "hailo-seg", "hailo-ocr", "hailo-reid", "hailo-clip",
                    "hailo-multisource", "hailo-tiling", "hailo_monitor_v3B.py"]
        for pat in patterns:
            subprocess.run(["pkill", "-f", pat])
        self._log("已发送终止信号给所有匹配的 hailo- 相关进程。")


if __name__ == "__main__":
    app = HailoTestGUI()
    app.mainloop()
