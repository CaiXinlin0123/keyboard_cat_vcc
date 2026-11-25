import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import messagebox, ttk


MAX_DRAWINGS = 10
MAX_PALETTES = 3
KEY_BASE = '#fafbf7'
KEY_ACCENTS = ('#a9cdec','#edaaaa','#c3dfa5','#f3c28b','#a7ded9')
ACCENT_NAMES = ('蓝色','红色','绿色','橙色','青色')
KEY_GROUPS = ('Tab、Enter、Ctrl','Esc、Backspace','Caps、Alt','Shift','空格')

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


def palette_slots(part,mode):
    if part=='鼠标':
        return ('鼠标',)
    base=(KEY_BASE,) if part=='键盘' else ()
    return base+(('single',) if mode=='single' else KEY_ACCENTS)


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
        drawings = data.get('drawings')
        self.drawings = [item for item in drawings if isinstance(item, dict)
                         and is_rgb(item.get('base')) and isinstance(item.get('png'), str)
                         and isinstance(item.get('name'), str)][:MAX_DRAWINGS] if isinstance(drawings,list) else []
        self.using_drawing = bool(self.drawings and data.get('using_drawing') is True)
        self.open_painter = None
        self.drawing_thumbnail = None
        self.menu_thumbnails = []
        size = data.get('size_percent')
        self.size_percent = size if type(size) is int and 50 <= size <= 175 else 100
        floating_style = data.get('floating_style')
        self.floating_style = tk.StringVar(root, value=floating_style if floating_style in
                                           ('bubble','text','black','white','custom','keycap') else 'black')
        custom_ink = data.get('floating_ink')
        self.floating_ink = custom_ink if is_rgb(custom_ink) else '#303030'
        self.keyboard_labels = tk.BooleanVar(root, value=data.get('keyboard_labels') is not False)
        self.body_shadow = tk.BooleanVar(root, value=data.get('body_shadow') is True)
        self.sync_themes = tk.BooleanVar(root, value=data.get('sync_themes') is not False)
        stored=data.get('palettes',{})
        self.palettes={}
        self.palette_windows={}
        for part in ('键盘','浮字按键提示'):
            record=stored.get(part) if isinstance(stored,dict) else None
            record=record if isinstance(record,dict) else {}
            palette={key:record.get(key) if is_rgb(record.get(key)) else key
                     for key in (KEY_BASE,)+KEY_ACCENTS}
            palette['single']=record['single'] if is_rgb(record.get('single')) else KEY_ACCENTS[0]
            palette['single_base']=record['single_base'] if is_rgb(record.get('single_base')) else palette[KEY_BASE]
            palette['mode']='single' if record.get('mode')=='single' else 'mixed'
            self.palettes[part]=palette
        stored_groups=data.get('palette_history',{})
        self.palette_history={}
        for part in ('键盘','鼠标','浮字按键提示'):
            for mode in (('single',) if part=='鼠标' else ('single','mixed')):
                group=part+'/'+mode
                items=stored_groups.get(group) if isinstance(stored_groups,dict) else None
                slots=palette_slots(part,mode)
                self.palette_history[group]=[item for item in items if isinstance(item,dict)
                    and isinstance(item.get('name'),str) and item['name'].strip()
                    and isinstance(item.get('colors'),dict) and all(is_rgb(item['colors'].get(k)) for k in slots)
                    ][:MAX_PALETTES] if isinstance(items,list) else []
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
        if self.using_drawing:
            self.variables['身体'].set('painted')

    def recent_drawings(self):
        return sorted(self.drawings,key=lambda d: d.get('last_used',0)
                      if type(d.get('last_used')) is int else 0,reverse=True)

    def active_drawing(self):
        return self.recent_drawings()[0] if self.using_drawing and self.drawings else None

    def use_drawing(self,record):
        if record not in self.drawings:
            return
        latest = self.recent_drawings()[0].get('last_used',0)
        previous_stamp=record.get('last_used')
        previous_active=self.using_drawing
        previous_choice=self.variables['身体'].get()
        record['last_used'] = (latest if type(latest) is int else 0) + 1
        self.using_drawing = True
        self.variables['身体'].set('painted')
        if self.save():
            return True
        if previous_stamp is None:
            record.pop('last_used',None)
        else:
            record['last_used']=previous_stamp
        self.using_drawing=previous_active
        self.variables['身体'].set(previous_choice)
        return False

    def select(self, part, color):
        if color is None:
            return
        if part == '身体':
            self.using_drawing = False
        recent = self.history[part]
        if color not in PRESETS[part].values():
            recent[:] = ([color] + [c for c in recent if c != color])[:5]
        self.current[part] = color
        self.variables[part].set(color)
        self.save()

    def save(self):
        data = {k: {'color': v, 'history': self.history[k]} for k,v in self.current.items()}
        data['floating_style'] = self.floating_style.get()
        data['size_percent'] = self.size_percent
        data['drawings'] = self.drawings
        data['using_drawing'] = self.using_drawing
        data['floating_ink'] = self.floating_ink
        data['keyboard_labels'] = self.keyboard_labels.get()
        data['body_shadow'] = self.body_shadow.get()
        data['sync_themes'] = self.sync_themes.get()
        data['themes'] = {part: theme.get() for part,theme in self.themes.items()}
        data['palettes'] = self.palettes
        data['palette_history'] = self.palette_history
        data['click_marks'] = self.click_marks.get()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            tmp.replace(self.path)
            return True
        except OSError as exc:
            messagebox.showerror('配色保存失败', str(exc), parent=self.root)
            return False

    def choose_floating_ink(self):
        color = pick_rgb(self.root, self.floating_ink, [])
        if color is not None:
            self.floating_ink = color
            self.floating_style.set('custom')
            self.save()

    def attach(self, menu, open_size=None):
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
        keyboard.add_command(label='自定义绘制',command=lambda:self.edit_palette('键盘'))
        self.add_theme(keyboard, '键盘')
        floating = tk.Menu(custom, tearoff=False)
        custom.add_cascade(label='浮字按键提示', menu=floating)
        floating.add_command(label='自定义绘制',command=lambda:self.edit_palette('浮字按键提示'))
        if open_size is not None:
            custom.add_command(label='小猫大小…', command=open_size)
        return floating

    def palette_color(self,part,slot):
        palette=self.palettes[part]
        key=slot
        if palette['mode']=='single':
            key='single_base' if slot==KEY_BASE else 'single'
        color=palette[key]
        return '#fe00ff' if color=='#ff00ff' else color

    def edit_palette(self,part):
        window=self.palette_windows.get(part)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        window=tk.Toplevel(self.root)
        self.palette_windows[part]=window
        window.title(part+' · 自定义绘制')
        window.attributes('-topmost',True)
        window.resizable(False,False)
        panel=ttk.Frame(window,padding=12)
        panel.pack()
        mouse=part=='鼠标'
        palette=self.current if mouse else self.palettes[part]
        mode=tk.StringVar(window,value='single' if mouse else palette['mode'])
        modes=ttk.Frame(panel)
        modes.pack(fill='x')
        rows=ttk.Frame(panel)
        rows.pack(fill='x',pady=(6,0))
        saved=ttk.LabelFrame(panel,text='最近保存的 3 套方案',padding=5)
        saved.pack(fill='x',pady=(8,0))
        history=ttk.Combobox(saved,state='readonly')
        history.pack(fill='x')
        naming=ttk.Frame(saved)
        naming.pack(fill='x',pady=(5,0))
        ttk.Label(naming,text='方案名').pack(side='left')
        name=ttk.Entry(naming,width=14)
        name.pack(side='left',fill='x',expand=True,padx=4)
        def group():
            return part+'/'+mode.get()
        def palette_key(slot):
            return 'single_base' if slot==KEY_BASE and mode.get()=='single' else slot
        def update_list():
            history.configure(values=[item['name'] for item in self.palette_history[group()]])
            history.set('')
        def store():
            title=name.get().strip() or datetime.now().strftime('%m-%d %H:%M:%S')
            snapshot={slot:palette[palette_key(slot)] for slot in palette_slots(part,mode.get())}
            old=self.palette_history[group()]
            others=[item for item in old if item['name']!=title]
            self.palette_history[group()]=[dict(name=title,colors=snapshot)]+others[:MAX_PALETTES-1]
            if not self.save():
                self.palette_history[group()]=old
                return
            update_list()
            history.current(0)
            name.delete(0,'end')
            name.insert(0,title)
        def restore(event):
            index=history.current()
            if index<0:
                return
            item=self.palette_history[group()][index]
            previous={palette_key(slot):palette[palette_key(slot)] for slot in palette_slots(part,mode.get())}
            for slot in palette_slots(part,mode.get()):
                palette[palette_key(slot)]=item['colors'][slot]
            if not self.save():
                palette.update(previous)
                history.set('')
                return
            if mouse:
                self.variables[part].set(palette[part])
                history.current(index)
            name.delete(0,'end')
            name.insert(0,item['name'])
            refresh()
        ttk.Button(naming,text='保存方案',command=store).pack(side='right')
        history.bind('<<ComboboxSelected>>',restore)
        def choose(key):
            color=pick_rgb(window,palette[key],[])
            if color is not None:
                if mouse:
                    self.select(part,color)
                else:
                    palette[key]=color
                    self.save()
                history.set('')
                refresh()
        def refresh():
            for child in rows.winfo_children():
                child.destroy()
            keyboard=part=='键盘'
            entries=[(palette_key(KEY_BASE),'底色（普通键和键盘外壳）')] if keyboard else []
            if mouse:
                entries.append((part,'鼠标颜色'))
            elif mode.get()=='single':
                entries.append(('single','特殊键颜色' if keyboard else '浮字颜色'))
            else:
                for i,key in enumerate(KEY_ACCENTS):
                    label=ACCENT_NAMES[i]
                    if keyboard:
                        label+=' · '+KEY_GROUPS[i]
                    entries.append((key,label))
            for i,(key,label) in enumerate(entries):
                ttk.Label(rows,text=label).grid(row=i,column=0,sticky='w',padx=(0,10),pady=3)
                swatch=palette[key]
                button=tk.Button(rows,bg=swatch,activebackground=swatch,width=8,text=swatch.upper(),
                                 fg='black' if sum(bytes.fromhex(swatch[1:]))>380 else 'white',
                                 command=lambda k=key:choose(k))
                button.grid(row=i,column=1,sticky='e')
        def switch():
            palette['mode']=mode.get()
            self.save()
            update_list()
            name.delete(0,'end')
            refresh()
        if not mouse:
            for label,value in [('纯色','single'),('混合','mixed')]:
                ttk.Radiobutton(modes,text=label,variable=mode,value=value,command=switch).pack(side='left',padx=3)
        else:
            def mouse_changed(*args):
                history.set('')
                window.after_idle(lambda:refresh() if window.winfo_exists() else None)
            variable=self.variables[part]
            token=variable.trace_add('write',mouse_changed)
            window.bind('<Destroy>',lambda e:variable.trace_remove('write',token) if e.widget==window else None)
        update_list()
        refresh()

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
            if self.open_painter:
                sub.add_command(label='自定义绘制', command=self.open_painter)
            for label,value in [('无阴影',0),('有阴影',1)]:
                sub.add_radiobutton(label=label, variable=self.body_shadow, value=value, command=self.save)
            sub.add_separator()
            sub.add_command(label='最近使用的自定义小猫',state='disabled')
            self.menu_thumbnails.clear()
            for item in self.recent_drawings()[:2]:
                image_options={}
                if self.drawing_thumbnail:
                    image=self.drawing_thumbnail(item,(30,36))
                    self.menu_thumbnails.append(image)
                    image_options=dict(image=image,compound='left')
                sub.add_command(label=item['name'],command=lambda cat=item:self.use_drawing(cat),
                                **image_options)
            return
        if part == '鼠标':
            sub.add_command(label='自定义绘制',command=lambda:self.edit_palette(part))
            self.add_theme(sub, part)
            sub.add_checkbutton(label='点击拟声线',variable=self.click_marks,command=self.save)
            sub.add_separator()
        sub.add_command(label='自定义 RGB…', command=choose)
        sub.add_separator()
        sub.add_command(label='最近使用的自定义颜色', state='disabled')
        for color in self.history[part]:
            choice(color.upper(),color)
