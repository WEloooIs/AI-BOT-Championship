from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tkinter as tk
import tomllib
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageTk
from instance_identity import INSTANCE_RESOLUTION_LOG, remove_instance_alias, resolve_instances, set_instance_alias
from ui_scrolling import ScrollableFrame as BaseScrollableFrame, install_mousewheel_support, register_mousewheel_target


BASE_DIR = Path(__file__).resolve().parent
ADB_EXE = BASE_DIR / "_internal" / "adbutils" / "binaries" / "adb.exe"
START_BAT = BASE_DIR / "start.bat"
GENERAL_CFG = BASE_DIR / "cfg" / "general_config.toml"
BOT_CFG = BASE_DIR / "cfg" / "bot_config.toml"
LATEST_BRAWLER_DATA = BASE_DIR / "latest_brawler_data.json"
RUNTIME_LOG = BASE_DIR / "pyla_runtime.log"
PROXY_LOG = BASE_DIR / "local_api_proxy.log"
HERO_ICON = BASE_DIR / "api" / "assets" / "brawler_icons2" / "barley.png"
PUSH_RUNTIME_DIR = BASE_DIR / "runtime_state" / "push"

BG = "#0e0f11"
SIDEBAR = "#101114"
PANEL = "#17181b"
PANEL_ALT = "#202228"
CARD_ACTIVE = "#281713"
BORDER = "#31333a"
ACCENT = "#d2452d"
ACCENT_HOVER = "#e15a41"
TEXT = "#f5efe8"
TEXT_SUBTLE = "#bcb5ae"
TEXT_MUTED = "#8c8580"


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def toml_literal(value: object) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def replace_toml_value(path: Path, key: str, value: object) -> None:
    content = path.read_text(encoding="utf-8")
    pattern = rf"(?m)^({re.escape(key)}\s*=\s*).*$"
    literal = toml_literal(value)
    updated, count = re.subn(pattern, lambda match: match.group(1) + literal, content)
    if count == 0:
        updated = content.rstrip() + f"\n{key} = {literal}\n"
    path.write_text(updated, encoding="utf-8")


def tail_text(path: Path, max_lines: int = 80) -> str:
    if not path.exists():
        return "Файл ещё не создан."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:]) or "Лог пуст."


def safe_run(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def coerce_port(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_entry_value(raw: str, caster, *, allow_auto: bool = False) -> object:
    value = raw.strip()
    if allow_auto and value.lower() == "auto":
        return "auto"
    return caster(value)


def make_instance_slug(instance: dict[str, str | int]) -> str:
    serial = str(instance.get("serial") or "unknown")
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", serial.replace(":", "_"))


def ensure_instance_runtime_state(instance: dict[str, str | int]) -> tuple[Path, Path]:
    slug = make_instance_slug(instance)
    runtime_dir = PUSH_RUNTIME_DIR / slug
    runtime_dir.mkdir(parents=True, exist_ok=True)
    latest_path = runtime_dir / "latest_brawler_data.json"
    log_path = runtime_dir / "pyla_runtime.log"
    if not latest_path.exists() and LATEST_BRAWLER_DATA.exists():
        shutil.copyfile(LATEST_BRAWLER_DATA, latest_path)
    return latest_path, log_path


def ensure_adb_started() -> None:
    if ADB_EXE.exists():
        safe_run([str(ADB_EXE), "start-server"], timeout=5)


def candidate_ports(current_port: int | None) -> list[int]:
    ports: list[int] = []
    if current_port:
        ports.append(current_port)
    ports.extend([16384, 16416, 16432, 5555, 5635])
    uniq: list[int] = []
    seen: set[int] = set()
    for port in ports:
        if port not in seen:
            uniq.append(port)
            seen.add(port)
    return uniq


def parse_model_from_line(line: str) -> str:
    match = re.search(r"model:([^\s]+)", line)
    if match:
        return match.group(1).replace("_", " ")
    return "Неизвестно"


def guess_emulator_name(serial: str, model: str) -> str:
    source = f"{serial} {model}".lower()
    if "ldplayer" in source:
        return "LDPlayer"
    if "bluestacks" in source or "hd-player" in source:
        return "BlueStacks"
    if "memu" in source:
        return "MEmu"
    if serial.startswith("emulator-"):
        return "Android Emulator"
    return "Others"


def detect_instances(current_port: int | None) -> list[dict[str, str | int]]:
    ensure_adb_started()
    result = safe_run([str(ADB_EXE), "devices", "-l"], timeout=5)
    if "127.0.0.1:" not in result.stdout:
        for port in candidate_ports(current_port):
            try:
                safe_run([str(ADB_EXE), "connect", f"127.0.0.1:{port}"], timeout=1)
            except Exception:
                pass
        result = safe_run([str(ADB_EXE), "devices", "-l"], timeout=5)
    items: list[dict[str, str | int]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]
        port = 0
        if serial.startswith("127.0.0.1:"):
            tail = serial.split(":", 1)[1]
            if tail.isdigit():
                port = int(tail)
        items.append(
            {
                "serial": serial,
                "port": port,
                "model": parse_model_from_line(line),
                "emulator": guess_emulator_name(serial, parse_model_from_line(line)),
            }
        )
    items.sort(key=lambda item: int(item["port"]) or 999999)
    return items


class ScrollFrame(BaseScrollableFrame):
    def __init__(self, master, bg_color: str) -> None:
        super().__init__(master, bg_color)
        self.inner = self.content


class SegmentControl(tk.Frame):
    def __init__(self, master, values: list[str], variable: tk.StringVar) -> None:
        super().__init__(master, bg=PANEL)
        self.variable = variable
        self.buttons: dict[str, tk.Button] = {}
        for idx, value in enumerate(values):
            button = tk.Button(
                self,
                text=value,
                command=lambda v=value: self.set(v),
                bg=PANEL_ALT,
                fg=TEXT,
                activebackground=ACCENT_HOVER,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                padx=14,
                pady=8,
                cursor="hand2",
                highlightthickness=0,
            )
            button.grid(row=0, column=idx, padx=(0 if idx == 0 else 8, 0), sticky="ew")
            self.grid_columnconfigure(idx, weight=1)
            self.buttons[value] = button
        self.refresh()

    def set(self, value: str) -> None:
        self.variable.set(value)
        self.refresh()

    def refresh(self) -> None:
        current = self.variable.get()
        for value, button in self.buttons.items():
            active = value == current
            button.configure(bg=ACCENT if active else PANEL_ALT, fg=TEXT)


class PylaHub(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Pyla Club Hub")
        self.geometry("1460x900")
        self.minsize(1240, 760)
        self.configure(bg=BG)
        install_mousewheel_support(self)

        self.general_config = read_toml(GENERAL_CFG)
        self.bot_config = read_toml(BOT_CFG)
        self.instances: list[dict[str, str | int]] = []
        self.selected_instance: dict[str, str | int] | None = None
        self.current_page = ""
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.setting_entries: dict[str, tk.Entry] = {}

        self.gamemode_var = tk.StringVar(value=str(self.bot_config.get("gamemode", "brawlball")))
        self.emulator_var = tk.StringVar(value=str(self.general_config.get("current_emulator", "Others")))
        self.client_variant_var = tk.StringVar(value=str(self.general_config.get("target_game_client", "official")))
        self.cpu_var = tk.StringVar(value=str(self.general_config.get("cpu_or_gpu", "auto")))
        self.longpress_var = tk.BooleanVar(value=str(self.general_config.get("long_press_star_drop", "yes")).lower() == "yes")
        self.alias_var = tk.StringVar()
        self._pulse_index = 0

        self._build_shell()
        self.refresh_instances()
        self.refresh_logs()
        self._animate_status()

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=SIDEBAR, width=280)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        content = tk.Frame(self, bg=BG)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self.content = content

        tk.Label(sidebar, text="PYLA", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 28, "bold")).pack(anchor="w", padx=24, pady=(28, 4))
        tk.Label(sidebar, text="Клубный хаб запуска", bg=SIDEBAR, fg=TEXT_SUBTLE, font=("Segoe UI", 12)).pack(anchor="w", padx=24)
        self.status_chip = tk.Label(sidebar, text="СИСТЕМА ГОТОВА", bg="#2a1612", fg=TEXT, font=("Segoe UI", 10, "bold"), padx=14, pady=8)
        self.status_chip.pack(anchor="w", padx=24, pady=(18, 24))

        nav = tk.Frame(sidebar, bg=SIDEBAR)
        nav.pack(fill="x", padx=16)
        self._make_nav(nav, "overview", "Обзор")
        self._make_nav(nav, "instances", "Инстансы")
        self._make_nav(nav, "settings", "Настройки")
        self._make_nav(nav, "logs", "Логи")

        tk.Label(
            sidebar,
            text="Хаб не ломает ядро pyla_main.exe.\nОн выбирает инстанс, пишет cfg и запускает start.bat.",
            bg=SIDEBAR,
            fg=TEXT_MUTED,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(side="bottom", anchor="w", padx=24, pady=24)

        header = tk.Frame(content, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 16))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Запуск на конкретный эмуляторный инстанс", bg=BG, fg=TEXT, font=("Segoe UI", 24, "bold")).grid(row=0, column=0, sticky="w")
        self.header_hint = tk.Label(header, text="Русский слой управления поверх текущего pyla_main.exe", bg=BG, fg=TEXT_SUBTLE, font=("Segoe UI", 11))
        self.header_hint.grid(row=0, column=1, sticky="e")

        container = tk.Frame(content, bg=BG)
        container.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 24))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)
        self.page_container = container

        self._build_overview_page()
        self._build_instances_page()
        self._build_settings_page()
        self._build_logs_page()
        self.show_page("overview")

    def _make_nav(self, parent, key: str, text: str) -> None:
        button = tk.Button(
            parent,
            text=text,
            command=lambda k=key: self.show_page(k),
            bg=SIDEBAR,
            fg=TEXT_SUBTLE,
            activebackground="#25140f",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            anchor="w",
            padx=18,
            pady=10,
            cursor="hand2",
            font=("Segoe UI", 12, "bold"),
        )
        button.pack(fill="x", pady=5)
        self.nav_buttons[key] = button

    def _panel(self, master) -> tk.Frame:
        return tk.Frame(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, bd=0)

    def _section_title(self, master, text: str) -> None:
        tk.Label(master, text=text, bg=PANEL, fg=TEXT, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20, pady=(18, 8))

    def _styled_button(self, master, text: str, command, accent: bool = False) -> tk.Button:
        return tk.Button(
            master,
            text=text,
            command=command,
            bg=ACCENT if accent else PANEL_ALT,
            fg=TEXT,
            activebackground=ACCENT_HOVER if accent else "#2c3037",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=16,
            pady=12,
            cursor="hand2",
            font=("Segoe UI", 11, "bold"),
        )

    def _build_overview_page(self) -> None:
        page = tk.Frame(self.page_container, bg=BG)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(1, weight=1)

        hero = self._panel(page)
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)

        top = tk.Frame(hero, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=24)
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="PC-клубный режим", bg=PANEL, fg=TEXT, font=("Segoe UI", 26, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            top,
            text="Выбираешь нужный ADB-порт, сохраняешь настройки и запускаешь бота ровно в этот инстанс.",
            bg=PANEL,
            fg=TEXT_SUBTLE,
            justify="left",
            font=("Segoe UI", 12),
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        if HERO_ICON.exists():
            image = Image.open(HERO_ICON).resize((88, 88))
            self.hero_photo = ImageTk.PhotoImage(image)
            tk.Label(top, image=self.hero_photo, bg=PANEL).grid(row=0, column=1, rowspan=2, sticky="e")

        self.selected_label = tk.Label(hero, text="Инстанс не выбран", bg=PANEL, fg=TEXT, font=("Segoe UI", 18, "bold"))
        self.selected_label.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 6))
        self.selected_meta = tk.Label(hero, text="Сначала нажми «Обновить инстансы».", bg=PANEL, fg=TEXT_MUTED, font=("Segoe UI", 11))
        self.selected_meta.grid(row=2, column=0, sticky="w", padx=24)

        alias_row = tk.Frame(hero, bg=PANEL)
        alias_row.grid(row=3, column=0, sticky="ew", padx=24, pady=(16, 0))
        alias_row.grid_columnconfigure(1, weight=1)
        tk.Label(alias_row, text="Alias инстанса", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.alias_entry = tk.Entry(alias_row, textvariable=self.alias_var, bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0)
        self.alias_entry.grid(row=0, column=1, sticky="ew", ipady=8)
        self._styled_button(alias_row, "Сохранить alias", self.save_selected_alias).grid(row=0, column=2, padx=(12, 8))
        self._styled_button(alias_row, "Сбросить", self.clear_selected_alias).grid(row=0, column=3)

        actions = tk.Frame(hero, bg=PANEL)
        actions.grid(row=4, column=0, sticky="ew", padx=24, pady=24)
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        self._styled_button(actions, "Обновить инстансы", self.refresh_instances).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._styled_button(actions, "Сохранить настройки", self.save_settings).grid(row=0, column=1, sticky="ew", padx=8)
        self._styled_button(actions, "Запустить бота", self.launch_bot, accent=True).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        quick = self._panel(page)
        quick.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
        self._section_title(quick, "Быстрые параметры")
        tk.Label(quick, text="Режим боя", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=20)
        self.gamemode_segment = SegmentControl(quick, ["brawlball", "other"], self.gamemode_var)
        self.gamemode_segment.pack(fill="x", padx=20, pady=(8, 16))
        tk.Label(quick, text="Эмулятор в конфиге", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=20)
        self.emu_segment = SegmentControl(quick, ["LDPlayer", "BlueStacks", "MEmu", "Others"], self.emulator_var)
        self.emu_segment.pack(fill="x", padx=20, pady=(8, 16))
        tk.Label(quick, text="Игровой клиент", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=20)
        self.client_segment = SegmentControl(quick, ["official", "nulls"], self.client_variant_var)
        self.client_segment.pack(fill="x", padx=20, pady=(8, 16))
        tk.Label(quick, text="Последний выбранный боец", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=20)
        self.latest_brawler_label = tk.Label(quick, text=self._format_latest_brawler(), bg=PANEL, fg=TEXT, justify="left", anchor="w", font=("Segoe UI", 11))
        self.latest_brawler_label.pack(fill="x", padx=20, pady=(8, 20))

        info = tk.Text(page, bg=PANEL, fg=TEXT, relief="flat", wrap="word", padx=20, pady=18, insertbackground=TEXT)
        info.grid(row=1, column=0, columnspan=2, sticky="nsew")
        register_mousewheel_target(info)
        info.insert(
            "1.0",
            "Поведение при вылете Brawl Stars:\n"
            "- если бот распознаёт экран play_store, он пытается ткнуть иконку Brawl Stars и вернуться в игру;\n"
            "- если срабатывает сценарий stuck / no detections, текущий restart_brawl_stars() не перезапускает игру, а завершает процесс;\n"
            "- то есть частичный автозаход есть, полноценного self-restart у процесса нет.\n",
        )
        info.configure(state="disabled")
        self.pages["overview"] = page

    def _build_instances_page(self) -> None:
        page = tk.Frame(self.page_container, bg=BG)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        top = self._panel(page)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._section_title(top, "ADB-инстансы")
        self.instances_hint = tk.Label(top, text="Список строится по adb devices -l и автоконнекту типовых локальных портов.", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11))
        self.instances_hint.pack(anchor="w", padx=20, pady=(0, 18))
        self.instances_scroll = ScrollFrame(page, PANEL)
        self.instances_scroll.grid(row=1, column=0, sticky="nsew")
        self.pages["instances"] = page

    def _build_settings_page(self) -> None:
        page = ScrollFrame(self.page_container, PANEL)
        page.grid(row=0, column=0, sticky="nsew")
        tk.Label(page.inner, text="Настройки бота", bg=PANEL, fg=TEXT, font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=22, pady=(20, 8))
        tk.Label(page.inner, text="Меняем понятные поля из cfg/*.toml и не лезем в ядро exe.", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=22, pady=(0, 18))

        settings = [
            ("minimum_movement_delay", "Минимальная задержка движения", str(self.bot_config.get("minimum_movement_delay", 0.05))),
            ("wall_detection_confidence", "Точность детекта стен", str(self.bot_config.get("wall_detection_confidence", 0.7))),
            ("entity_detection_confidence", "Точность детекта врагов", str(self.bot_config.get("entity_detection_confidence", 0.5))),
            ("unstuck_movement_delay", "Задержка анти-стак", str(self.bot_config.get("unstuck_movement_delay", 3.0))),
            ("unstuck_movement_hold_time", "Длительность анти-стак", str(self.bot_config.get("unstuck_movement_hold_time", 1.5))),
            ("super_pixels_minimum", "Порог супер-способности", str(self.bot_config.get("super_pixels_minimum", 2000.0))),
            ("gadget_pixels_minimum", "Порог гаджета", str(self.bot_config.get("gadget_pixels_minimum", 2000.0))),
            ("hypercharge_pixels_minimum", "Порог гиперзаряда", str(self.bot_config.get("hypercharge_pixels_minimum", 2000.0))),
            ("max_ips", "Максимальный IPS", str(self.general_config.get("max_ips", 60))),
            ("run_for_minutes", "Работать минут", str(self.general_config.get("run_for_minutes", 600))),
            ("trophies_multiplier", "Множитель трофеев", str(self.general_config.get("trophies_multiplier", 1))),
        ]

        for key, label, value in settings:
            row = tk.Frame(page.inner, bg=PANEL)
            row.pack(fill="x", padx=22, pady=8)
            tk.Label(row, text=label, bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(side="left")
            entry = tk.Entry(row, bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, width=18)
            entry.insert(0, value)
            entry.pack(side="right", ipady=6)
            self.setting_entries[key] = entry

        cpu_row = tk.Frame(page.inner, bg=PANEL)
        cpu_row.pack(fill="x", padx=22, pady=8)
        tk.Label(cpu_row, text="Режим вычислений", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(side="left")
        cpu_menu = tk.OptionMenu(cpu_row, self.cpu_var, "auto", "cpu")
        cpu_menu.configure(bg=ACCENT, fg=TEXT, activebackground=ACCENT_HOVER, activeforeground=TEXT, relief="flat", highlightthickness=0)
        cpu_menu["menu"].configure(bg=PANEL_ALT, fg=TEXT)
        cpu_menu.pack(side="right")

        client_row = tk.Frame(page.inner, bg=PANEL)
        client_row.pack(fill="x", padx=22, pady=8)
        tk.Label(client_row, text="Игровой клиент для recovery", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(side="left")
        client_menu = tk.OptionMenu(client_row, self.client_variant_var, "official", "nulls")
        client_menu.configure(bg=ACCENT, fg=TEXT, activebackground=ACCENT_HOVER, activeforeground=TEXT, relief="flat", highlightthickness=0)
        client_menu["menu"].configure(bg=PANEL_ALT, fg=TEXT)
        client_menu.pack(side="right")

        long_row = tk.Frame(page.inner, bg=PANEL)
        long_row.pack(fill="x", padx=22, pady=8)
        tk.Label(long_row, text="Longpress star_drop", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(side="left")
        tk.Checkbutton(long_row, variable=self.longpress_var, bg=PANEL, fg=TEXT, selectcolor=PANEL_ALT, activebackground=PANEL, activeforeground=TEXT).pack(side="right")

        self._styled_button(page.inner, "Сохранить настройки", self.save_settings, accent=True).pack(fill="x", padx=22, pady=(18, 22))
        self.pages["settings"] = page

    def _build_logs_page(self) -> None:
        page = tk.Frame(self.page_container, bg=BG)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure((0, 1, 2), weight=1)
        top = tk.Frame(page, bg=BG)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Последние логи", bg=BG, fg=TEXT, font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        self._styled_button(top, "Обновить", self.refresh_logs).grid(row=0, column=1, sticky="e")
        self.runtime_box = tk.Text(page, bg=PANEL, fg=TEXT, relief="flat", wrap="word", padx=16, pady=14, insertbackground=TEXT)
        self.runtime_box.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.proxy_box = tk.Text(page, bg=PANEL, fg=TEXT, relief="flat", wrap="word", padx=16, pady=14, insertbackground=TEXT)
        self.proxy_box.grid(row=1, column=1, sticky="nsew", padx=8)
        self.instance_box = tk.Text(page, bg=PANEL, fg=TEXT, relief="flat", wrap="word", padx=16, pady=14, insertbackground=TEXT)
        self.instance_box.grid(row=1, column=2, sticky="nsew", padx=(8, 0))
        register_mousewheel_target(self.runtime_box)
        register_mousewheel_target(self.proxy_box)
        register_mousewheel_target(self.instance_box)
        self.pages["logs"] = page

    def show_page(self, key: str) -> None:
        self.current_page = key
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(bg="#25140f" if active else SIDEBAR, fg=TEXT if active else TEXT_SUBTLE)

    def _animate_status(self) -> None:
        colors = ["#2a1612", "#351a14", "#421d16", "#351a14"]
        self.status_chip.configure(bg=colors[self._pulse_index % len(colors)])
        self._pulse_index += 1
        self.after(320, self._animate_status)

    def _format_latest_brawler(self) -> str:
        if not LATEST_BRAWLER_DATA.exists():
            return "Данные ещё не выбраны."
        try:
            data = json.loads(LATEST_BRAWLER_DATA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "latest_brawler_data.json повреждён."
        if not data:
            return "Список пуст."
        entry = data[0]
        mode = "трофеи" if entry.get("type") == "trophies" else "победы"
        return (
            f"Боец: {entry.get('brawler', '—')}\n"
            f"Цель: {entry.get('push_until', '—')} ({mode})\n"
            f"Сейчас: {entry.get('trophies', '—')} трофеев / {entry.get('wins', '—')} побед"
        )

    def refresh_instances(self) -> None:
        current_port = coerce_port(self.general_config.get("emulator_port", 0), 0)
        preferred_serial = str(self.selected_instance["serial"]) if self.selected_instance else ""
        self.instances = resolve_instances(current_port)
        self.selected_instance = None
        for instance in self.instances:
            if preferred_serial and str(instance["serial"]) == preferred_serial:
                self.selected_instance = instance
                break
        if self.selected_instance is None:
            for instance in self.instances:
                if current_port and int(instance["port"]) == current_port:
                    self.selected_instance = instance
                    break
        if self.selected_instance is None and self.instances:
            self.selected_instance = self.instances[0]

        for child in self.instances_scroll.inner.winfo_children():
            child.destroy()

        if not self.instances:
            tk.Label(self.instances_scroll.inner, text="ADB-инстансы не найдены. Запусти эмулятор и обнови список.", bg=PANEL, fg=TEXT_SUBTLE, font=("Segoe UI", 12)).pack(anchor="w", padx=20, pady=20)
        else:
            for instance in self.instances:
                active = self.selected_instance == instance
                card = tk.Frame(self.instances_scroll.inner, bg=CARD_ACTIVE if active else PANEL_ALT, highlightbackground=ACCENT if active else BORDER, highlightthickness=1)
                card.pack(fill="x", padx=16, pady=10)
                info = tk.Frame(card, bg=card["bg"])
                info.pack(side="left", fill="both", expand=True, padx=18, pady=14)
                tk.Label(info, text=f"{instance['emulator']}  •  {instance['serial']}", bg=card["bg"], fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w")
                tk.Label(info, text=f"Порт: {instance['port'] or 'n/a'}    Модель: {instance['model']}", bg=card["bg"], fg=TEXT_SUBTLE, font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
                self._styled_button(card, "Выбран" if active else "Выбрать", lambda item=instance: self.select_instance(item), accent=active).pack(side="right", padx=18, pady=18)

        if self.instances:
            self.instances_hint.configure(text=f"Найдено {len(self.instances)} инстанс(ов). Точный адресный запуск работает для 127.0.0.1:PORT.")
        else:
            self.instances_hint.configure(text="Список строится по adb devices -l и автоконнекту типовых локальных портов.")
        self._update_selected_ui()

    def select_instance(self, instance: dict[str, str | int]) -> None:
        self.selected_instance = instance
        self.emulator_var.set(str(instance["emulator"]))
        self.emu_segment.refresh()
        self.refresh_instances()

    def _update_selected_ui(self) -> None:
        if not self.selected_instance:
            self.selected_label.configure(text="Инстанс не выбран")
            self.selected_meta.configure(text="Сначала нажми «Обновить инстансы».")
        else:
            item = self.selected_instance
            self.selected_label.configure(text=f"{item['emulator']} • {item['serial']}")
            if coerce_port(item["port"]):
                self.selected_meta.configure(text=f"Порт {item['port']}  •  модель {item['model']}  •  запуск пойдёт именно сюда")
            else:
                self.selected_meta.configure(text=f"У этого инстанса нет TCP-порта  •  модель {item['model']}  •  адресный запуск недоступен")
        self.latest_brawler_label.configure(text=self._format_latest_brawler())

    def save_settings(self) -> bool:
        try:
            bot_keys = {
                "minimum_movement_delay": float,
                "wall_detection_confidence": float,
                "entity_detection_confidence": float,
                "unstuck_movement_delay": float,
                "unstuck_movement_hold_time": float,
                "super_pixels_minimum": float,
                "gadget_pixels_minimum": float,
                "hypercharge_pixels_minimum": float,
            }
            general_keys = {
                "max_ips": (int, True),
                "run_for_minutes": (int, False),
                "trophies_multiplier": (int, False),
            }
            for key, caster in bot_keys.items():
                replace_toml_value(BOT_CFG, key, parse_entry_value(self.setting_entries[key].get(), caster))
            for key, (caster, allow_auto) in general_keys.items():
                replace_toml_value(
                    GENERAL_CFG,
                    key,
                    parse_entry_value(self.setting_entries[key].get(), caster, allow_auto=allow_auto),
                )
            replace_toml_value(BOT_CFG, "gamemode", self.gamemode_var.get())
            replace_toml_value(GENERAL_CFG, "current_emulator", self.emulator_var.get())
            replace_toml_value(GENERAL_CFG, "target_game_client", self.client_variant_var.get())
            replace_toml_value(GENERAL_CFG, "cpu_or_gpu", self.cpu_var.get())
            replace_toml_value(GENERAL_CFG, "long_press_star_drop", "yes" if self.longpress_var.get() else "no")
            if self.selected_instance and coerce_port(self.selected_instance["port"]):
                replace_toml_value(GENERAL_CFG, "emulator_port", coerce_port(self.selected_instance["port"]))
            self.general_config = read_toml(GENERAL_CFG)
            self.bot_config = read_toml(BOT_CFG)
            self.header_hint.configure(text="Настройки сохранены.")
            return True
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))
            return False

    def launch_bot(self) -> None:
        if not self.save_settings():
            return
        env = os.environ.copy()
        if self.selected_instance:
            if not coerce_port(self.selected_instance["port"]):
                messagebox.showwarning("Нужен TCP-инстанс", "Для точного запуска выбери инстанс вида 127.0.0.1:PORT.")
                return
            env["PYLA_EMULATOR_PORT"] = str(self.selected_instance["port"])
            env["PYLA_CURRENT_EMULATOR"] = str(self.selected_instance["emulator"])
        subprocess.Popen(
            ["cmd.exe", "/k", str(START_BAT)],
            cwd=BASE_DIR,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self.header_hint.configure(text="Бот запущен в новом окне. Внутренний GUI выбора бойца откроется уже на выбранный инстанс.")

    def refresh_logs(self) -> None:
        self.runtime_box.delete("1.0", "end")
        self.runtime_box.insert("1.0", "pyla_runtime.log\n\n" + tail_text(RUNTIME_LOG))
        self.proxy_box.delete("1.0", "end")
        self.proxy_box.insert("1.0", "local_api_proxy.log\n\n" + tail_text(PROXY_LOG))

    def refresh_instances(self) -> None:
        current_port = coerce_port(self.general_config.get("emulator_port", 0), 0)
        self.instances = resolve_instances(current_port)
        self.selected_instance = None
        for instance in self.instances:
            if current_port and coerce_port(instance["port"]) == current_port:
                self.selected_instance = instance
                break
        if self.selected_instance is None and self.instances:
            self.selected_instance = self.instances[0]

        for child in self.instances_scroll.inner.winfo_children():
            child.destroy()

        if not self.instances:
            tk.Label(
                self.instances_scroll.inner,
                text="ADB-инстансы не найдены. Запусти эмулятор и обнови список.",
                bg=PANEL,
                fg=TEXT_SUBTLE,
                font=("Segoe UI", 12),
            ).pack(anchor="w", padx=20, pady=20)
        else:
            for instance in self.instances:
                active = self.selected_instance == instance
                card = tk.Frame(
                    self.instances_scroll.inner,
                    bg=CARD_ACTIVE if active else PANEL_ALT,
                    highlightbackground=ACCENT if active else BORDER,
                    highlightthickness=1,
                )
                card.pack(fill="x", padx=16, pady=10)
                info = tk.Frame(card, bg=card["bg"])
                info.pack(side="left", fill="both", expand=True, padx=18, pady=14)
                tk.Label(info, text=str(instance["display_label"]), bg=card["bg"], fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w")
                tk.Label(info, text=f"Serial: {instance['serial']}    Vendor: {instance['vendor']}", bg=card["bg"], fg=TEXT_SUBTLE, font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
                tk.Label(info, text=f"Порт: {instance['port'] or 'n/a'}    Модель: {instance['model']}", bg=card["bg"], fg=TEXT_SUBTLE, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
                tk.Label(info, text=f"Source: {instance['resolved_name_source']}    Match: {float(instance['match_confidence']):.2f}", bg=card["bg"], fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
                self._styled_button(card, "Выбран" if active else "Выбрать", lambda item=instance: self.select_instance(item), accent=active).pack(side="right", padx=18, pady=18)

        if self.instances:
            self.instances_hint.configure(text=f"Найдено {len(self.instances)} инстанс(ов). Display label строится через alias -> vendor metadata -> window title -> fallback.")
        else:
            self.instances_hint.configure(text="Список строится по adb devices -l, vendor-specific metadata и window-title resolution.")
        self._update_selected_ui()

    def select_instance(self, instance: dict[str, str | int]) -> None:
        self.selected_instance = instance
        self.emulator_var.set(str(instance.get("config_emulator_name") or "Others"))
        self.emu_segment.refresh()
        self._render_instances_selection_only(preserve_scroll=True)

    def _update_selected_ui(self) -> None:
        if not self.selected_instance:
            self.selected_label.configure(text="Инстанс не выбран")
            self.selected_meta.configure(text="Сначала нажми «Обновить инстансы».")
            self.alias_var.set("")
        else:
            item = self.selected_instance
            self.selected_label.configure(text=str(item["display_label"]))
            self.selected_meta.configure(
                text=(
                    f"Serial {item['serial']}  •  vendor {item['vendor']}  •  модель {item['model']}  •  "
                    f"source {item['resolved_name_source']}  •  match {float(item['match_confidence']):.2f}"
                )
            )
            self.alias_var.set(str(item.get("alias") or ""))
        self.latest_brawler_label.configure(text=self._format_latest_brawler())

    def save_selected_alias(self) -> None:
        if not self.selected_instance:
            messagebox.showwarning("Нет инстанса", "Сначала выбери инстанс.")
            return
        alias = self.alias_var.get().strip()
        if not alias:
            messagebox.showwarning("Пустой alias", "Введи alias или используй сброс.")
            return
        instance_key = self.selected_instance.get("instance_id")
        set_instance_alias(str(self.selected_instance["serial"]), alias, str(instance_key) if instance_key else None)
        self.header_hint.configure(text=f"Alias сохранён: {alias}")
        self.refresh_instances()

    def clear_selected_alias(self) -> None:
        if not self.selected_instance:
            messagebox.showwarning("Нет инстанса", "Сначала выбери инстанс.")
            return
        instance_key = self.selected_instance.get("instance_id")
        remove_instance_alias(str(self.selected_instance["serial"]), str(instance_key) if instance_key else None)
        self.header_hint.configure(text="Alias сброшен. Используется auto-resolve.")
        self.refresh_instances()

    def launch_bot(self) -> None:
        if not self.save_settings():
            return
        env = os.environ.copy()
        if self.selected_instance:
            if not coerce_port(self.selected_instance["port"]):
                messagebox.showwarning("Нужен TCP-инстанс", "Для точного запуска выбери инстанс вида 127.0.0.1:PORT.")
                return
            latest_path, log_path = ensure_instance_runtime_state(self.selected_instance)
            env["PYLA_MULTI_PUSH"] = "1"
            env["PYLA_INSTANCE_SERIAL"] = str(self.selected_instance["serial"])
            env["PYLA_EMULATOR_PORT"] = str(self.selected_instance["port"])
            env["PYLA_CURRENT_EMULATOR"] = str(self.selected_instance["vendor"])
            env["PYLA_TARGET_GAME_CLIENT"] = self.client_variant_var.get().strip() or "official"
            env["PYLA_LATEST_BRAWLER_DATA_PATH"] = str(latest_path)
            env["PYLA_RUNTIME_LOG_PATH"] = str(log_path)
            env.pop("PYLA_START_FROM_LATEST", None)
        subprocess.Popen(
            ["cmd.exe", "/k", str(START_BAT)],
            cwd=BASE_DIR,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self.header_hint.configure(text="Бот запущен в новом окне на выбранный инстанс.")

    def refresh_logs(self) -> None:
        self.runtime_box.delete("1.0", "end")
        self.runtime_box.insert("1.0", "pyla_runtime.log\n\n" + tail_text(RUNTIME_LOG))
        self.proxy_box.delete("1.0", "end")
        self.proxy_box.insert("1.0", "local_api_proxy.log\n\n" + tail_text(PROXY_LOG))
        self.instance_box.delete("1.0", "end")
        self.instance_box.insert("1.0", "instance_resolution.log\n\n" + tail_text(INSTANCE_RESOLUTION_LOG, max_lines=200))

    def _render_instances_selection_only(self, preserve_scroll: bool = True) -> None:
        scroll_fraction = 0.0
        if preserve_scroll:
            try:
                scroll_fraction = float(self.instances_scroll.canvas.yview()[0])
            except Exception:
                scroll_fraction = 0.0

        for child in self.instances_scroll.inner.winfo_children():
            child.destroy()

        if not self.instances:
            tk.Label(
                self.instances_scroll.inner,
                text="ADB-инстансы не найдены. Запусти эмулятор и обнови список.",
                bg=PANEL,
                fg=TEXT_SUBTLE,
                font=("Segoe UI", 12),
            ).pack(anchor="w", padx=20, pady=20)
        else:
            for instance in self.instances:
                active = self.selected_instance == instance
                card = tk.Frame(
                    self.instances_scroll.inner,
                    bg=CARD_ACTIVE if active else PANEL_ALT,
                    highlightbackground=ACCENT if active else BORDER,
                    highlightthickness=1,
                )
                card.pack(fill="x", padx=16, pady=10)
                info = tk.Frame(card, bg=card["bg"])
                info.pack(side="left", fill="both", expand=True, padx=18, pady=14)
                tk.Label(info, text=str(instance["display_label"]), bg=card["bg"], fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w")
                tk.Label(info, text=f"Serial: {instance['serial']}    Vendor: {instance['vendor']}", bg=card["bg"], fg=TEXT_SUBTLE, font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
                tk.Label(info, text=f"Порт: {instance['port'] or 'n/a'}    Модель: {instance['model']}", bg=card["bg"], fg=TEXT_SUBTLE, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
                tk.Label(info, text=f"Source: {instance['resolved_name_source']}    Match: {float(instance['match_confidence']):.2f}", bg=card["bg"], fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
                self._styled_button(card, "Выбран" if active else "Выбрать", lambda item=instance: self.select_instance(item), accent=active).pack(side="right", padx=18, pady=18)

        self._update_selected_ui()
        if preserve_scroll:
            self.update_idletasks()
            try:
                self.instances_scroll.canvas.yview_moveto(scroll_fraction)
            except Exception:
                pass


def main() -> None:
    app = PylaHub()
    app.mainloop()


if __name__ == "__main__":
    main()
