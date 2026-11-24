import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import messagebox


PRESETS = {
    '眼睛': {'黄色': '#edc95b', '绿色': '#d2e85a', '蓝色': '#80bbef'},
    '瞳孔': {'黑色': '#090909', '白色': '#ffffff'},
    '身体': {'黑色': '#151515', '白色': '#f3f1eb', '橘色': '#e39650', '三花猫': 'calico',
           '奶牛猫牛多': 'tuxedo', '奶牛猫奶多': 'tuxedo_white',
           '橘白猫': 'ginger_white', '狸花猫': 'tabby'},
    '鼠标': {'蓝色': '#a9cdec', '粉色': '#edaaaa', '绿色': '#c3dfa5',
           '橙色': '#f3c28b', '青色': '#a7ded9', '白色': '#fafbf7'},
}


def is_rgb(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-f]{6}', value) is not None


class ChooseColor(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('owner', wintypes.HWND),
                ('instance', wintypes.HWND), ('rgb', wintypes.DWORD),
                ('custom', ctypes.POINTER(wintypes.DWORD)), ('flags', wintypes.DWORD),
                ('data', wintypes.LPARAM), ('hook', ctypes.c_void_p), ('template', wintypes.LPCWSTR)]


def pick_rgb(root, initial, history):
    def colorref(hex_color):
        return int.from_bytes(bytes.fromhex(hex_color[1:]), 'little')
    slots = (wintypes.DWORD * 16)(*[colorref(c) for c in history + ['#ffffff']*(16-len(history))])
    dlg = ChooseColor()
    dlg.size = ctypes.sizeof(dlg)
    dlg.owner = root.winfo_id()
    dlg.rgb = colorref(initial)
    dlg.custom = slots
    dlg.flags = 3  # Start with the current RGB and open the full colour spectrum.
    if ctypes.windll.comdlg32.ChooseColorW(ctypes.byref(dlg)):
        return '#' + dlg.rgb.to_bytes(3, 'little').hex()


class CatColors:
    def __init__(self, root, path=None):
        self.root = root
        self.path = path or Path(os.environ['LOCALAPPDATA']) / 'BlackCatPet' / 'colors.json'
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.current, self.history, self.variables, self.menus = {}, {}, {}, {}
        floating_style = data.get('floating_style')
        self.floating_style = tk.StringVar(root, value=floating_style if floating_style in
                                           ('bubble','black','white','custom','keycap') else 'black')
        custom_ink = data.get('floating_ink')
        self.floating_ink = custom_ink if is_rgb(custom_ink) else '#303030'
        self.keyboard_labels = tk.BooleanVar(root, value=data.get('keyboard_labels') is not False)
        self.body_shadow = tk.BooleanVar(root, value=data.get('body_shadow') is True)
        self.sync_themes = tk.BooleanVar(root, value=data.get('sync_themes') is not False)
        saved_themes = data.get('themes', {})
        if not isinstance(saved_themes, dict):
            saved_themes = {}
        old_dark = data.get('dark_mode') is True
        self.themes = {}
        for part in ('键盘','鼠标','浮字按键提示'):
            source = '键盘' if self.sync_themes.get() else part
            self.themes[part] = tk.BooleanVar(root, value=saved_themes.get(source, old_dark) is True)
        self.click_marks = tk.BooleanVar(root, value=data.get('click_marks') is not False)
        for part, presets in PRESETS.items():
            record = data.get(part, {})
            if not isinstance(record, dict):
                record = {}
            value = record.get('color')
            self.current[part] = value if is_rgb(value) or value in presets.values() else next(iter(presets.values()))
            recent = record.get('history', [])
            self.history[part] = list(dict.fromkeys(c for c in recent if is_rgb(c) and c not in presets.values()))[:5] if isinstance(recent,list) else []
            self.variables[part] = tk.StringVar(root, value=self.current[part])

    def select(self, part, color):
        if color is None:
            return
        recent = self.history[part]
        if color not in PRESETS[part].values():
            recent[:] = ([color] + [c for c in recent if c != color])[:5]
        self.current[part] = color
        self.variables[part].set(color)
        self.save()

    def save(self):
        data = {k: {'color': v, 'history': self.history[k]} for k,v in self.current.items()}
        data['floating_style'] = self.floating_style.get()
        data['floating_ink'] = self.floating_ink
        data['keyboard_labels'] = self.keyboard_labels.get()
        data['body_shadow'] = self.body_shadow.get()
        data['sync_themes'] = self.sync_themes.get()
        data['themes'] = {part: theme.get() for part,theme in self.themes.items()}
        data['click_marks'] = self.click_marks.get()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            tmp.replace(self.path)
        except OSError as exc:
            messagebox.showerror('配色保存失败', str(exc), parent=self.root)

    def choose_floating_ink(self):
        color = pick_rgb(self.root, self.floating_ink, [])
        if color is not None:
            self.floating_ink = color
            self.floating_style.set('custom')
            self.save()

    def attach(self, menu):
        custom = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label='自定义', menu=custom)
        for part in PRESETS:
            parent = self.menus['眼睛'] if part == '瞳孔' else custom
            sub = tk.Menu(parent, tearoff=False, postcommand=lambda p=part: self.fill_menu(p))
            self.menus[part] = sub
            if part != '瞳孔':
                custom.add_cascade(label=part, menu=sub)
        for part in PRESETS:
            self.fill_menu(part)
        keyboard = tk.Menu(custom, tearoff=False)
        custom.add_cascade(label='键盘', menu=keyboard)
        keyboard.add_checkbutton(label='显示按键',variable=self.keyboard_labels,command=self.save)
        self.add_theme(keyboard, '键盘')
        floating = tk.Menu(custom, tearoff=False)
        custom.add_cascade(label='浮字按键提示', menu=floating)
        return floating

    def apply_theme(self, part):
        if self.sync_themes.get():
            dark = self.themes[part].get()
            for theme in self.themes.values():
                theme.set(dark)
        self.save()

    def add_theme(self, menu, part):
        menu.add_separator()
        for label,value in [('浅色',0),('深色',1)]:
            menu.add_radiobutton(label=label,variable=self.themes[part],value=value,
                                 command=lambda: self.apply_theme(part))
        menu.add_checkbutton(label='键鼠字协同',variable=self.sync_themes,
                             command=lambda: self.apply_theme(part))

    def fill_menu(self, part):
        sub = self.menus[part]
        sub.delete(0, 'end')
        def choice(label, color):
            sub.add_radiobutton(label=label, value=color, variable=self.variables[part],
                                command=lambda: self.select(part,color))
        for label,color in PRESETS[part].items():
            choice(label,color)
        def choose():
            current = self.current[part]
            self.select(part,pick_rgb(self.root, current if is_rgb(current) else '#f3f1eb', self.history[part]))
        sub.add_separator()
        if part == '眼睛':
            sub.add_cascade(label='瞳孔', menu=self.menus['瞳孔'])
            sub.add_separator()
        if part == '身体':
            for label,value in [('无阴影',0),('有阴影',1)]:
                sub.add_radiobutton(label=label, variable=self.body_shadow, value=value, command=self.save)
            sub.add_separator()
        if part == '鼠标':
            self.add_theme(sub, part)
            sub.add_checkbutton(label='点击拟声线',variable=self.click_marks,command=self.save)
            sub.add_separator()
        sub.add_command(label='自定义 RGB…', command=choose)
        sub.add_separator()
        sub.add_command(label='最近使用的自定义颜色', state='disabled')
        for color in self.history[part]:
            choice(color.upper(),color)
