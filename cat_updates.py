import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


VERSION = '1.4.1'
REPOSITORY = 'https://github.com/CaiXinlin0123/keyboard_cat_vcc'
WINDOWS_PACKAGE = 'keyboard-cat-windows-x64.zip'
DAY_MS = 24 * 60 * 60 * 1000


def latest_windows_tag(releases):
    if not isinstance(releases, list):
        raise ValueError('Invalid release list')
    versions = {}
    for release in releases:
        tag = release['tag_name']
        if release['draft'] or release['prerelease'] or not re.fullmatch(r'v?[0-9]+\.[0-9]+\.[0-9]+', tag):
            continue
        if any(a['name'] == WINDOWS_PACKAGE and a['state'] == 'uploaded' for a in release['assets']):
            versions[tuple(map(int, tag.lstrip('v').split('.')))] = tag
    if not versions:
        raise ValueError('No Windows release')
    return versions[max(versions)]


def fetch_windows_tag():
    # The portable Python omits OpenSSL. Use Windows HTTPS and its trusted roots.
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = """
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$reply = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -UserAgent 'Keyboard-Cat-VCC' -Uri 'https://api.github.com/repos/CaiXinlin0123/keyboard_cat_vcc/releases?per_page=100'
[Console]::Write($reply.Content)
"""
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, timeout=16, check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return latest_windows_tag(json.loads(result.stdout))


class UpdateReminder:
    def __init__(self, root, settings_dir):
        self.root = root
        self.seen = settings_dir / 'last-update-notice.txt'
        self.results = queue.Queue()
        self.checking = self.manual = False
        self.window = None

    def daily(self):
        self.check()
        self.root.after(DAY_MS, self.daily)

    def check(self, manual=False):
        if self.window is not None and self.window.winfo_exists():
            if manual:
                self.window.lift()
            return
        self.manual |= manual
        if self.checking:
            return
        self.checking = True
        threading.Thread(target=self._fetch, daemon=True).start()
        self.root.after(150, self._finish)

    def _fetch(self):
        try:
            tag = fetch_windows_tag()
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            tag = None
        self.results.put(tag)

    def _finish(self):
        try:
            tag = self.results.get_nowait()
        except queue.Empty:
            self.root.after(150, self._finish)
            return
        manual, self.manual, self.checking = self.manual, False, False
        if tag is None:
            if manual:
                messagebox.showinfo('检查更新', '暂时无法获取 Windows 发行信息，请稍后再试。', parent=self.root)
            return
        if tuple(map(int, tag.lstrip('v').split('.'))) <= tuple(map(int, VERSION.split('.'))):
            if manual:
                messagebox.showinfo('检查更新', f'当前版本 v{VERSION}，暂时没有更新的 Windows 正式版。', parent=self.root)
            return
        try:
            if not manual and self.seen.is_file() and self.seen.read_text(encoding='utf-8') == tag:
                return
        except (OSError, UnicodeError):
            pass
        self._show(tag)
        try:
            self.seen.parent.mkdir(parents=True, exist_ok=True)
            self.seen.write_text(tag, encoding='utf-8')
        except OSError:
            pass

    def _show(self, tag):
        window = self.window = tk.Toplevel(self.root)
        window.title('小猫 VCC · 更新提醒')
        window.resizable(False, False)
        window.attributes('-topmost', True)
        panel = ttk.Frame(window, padding=16)
        panel.pack()
        ttk.Label(panel, text=f'小猫有新版啦！  v{VERSION} → {tag}').pack(anchor='w')
        ttk.Label(panel, text='去 GitHub 看看新玩法，或稍后从右键菜单检查更新。').pack(pady=(6, 14))
        buttons = ttk.Frame(panel)
        buttons.pack(anchor='e')

        def open_release():
            try:
                os.startfile(f'{REPOSITORY}/releases/tag/{tag}')
            except OSError:
                messagebox.showerror('打开下载页', '无法打开浏览器，请到项目的 Releases 页面下载。', parent=window)
                return
            window.destroy()

        ttk.Button(buttons, text='稍后', command=window.destroy).pack(side='left', padx=5)
        ttk.Button(buttons, text='查看更新并下载', command=open_release).pack(side='left')
