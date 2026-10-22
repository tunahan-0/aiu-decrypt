import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import customtkinter as ctk
from customtkinter import filedialog

from decrypter import PackageDecryptionService

# ──────── Tema ────────
BG = "#0E1016"
CARD = "#171A23"
CARD_BORDER = "#252a38"
INPUT_BG = "#0E1016"
ACCENT = "#7C5CFF"
ACCENT_HOVER = "#6A49F0"
GHOST_HOVER = "#232838"
TEXT = "#E8EAF2"
MUTED = "#8189A0"
SUCCESS = "#3DDC97"
ERROR = "#FF5C7A"
WARN = "#FFC857"

FONT = "Segoe UI"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ──────── Yardımcılar ────────
def app_dir() -> Path:
    """Script'in (veya paketlenmiş exe'nin) bulunduğu klasör."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def get_config_path() -> str:
    """Config dosyasını Windows AppData/Roaming altına kaydeder."""
    if sys.platform.startswith("win"):
        base_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "aiuDecrypt")
    else:
        base_dir = os.path.join(os.path.expanduser("~"), ".config", "aiuDecrypt")

    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "config.json")

CONFIG_FILE = get_config_path()


def open_folder(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def existing_dir(path: str) -> str | None:
    """Verilen yol bir klasörse onu, dosyaysa üst klasörünü, yoksa None döndürür."""
    if not path:
        return None
    p = Path(path)
    if p.is_dir():
        return str(p)
    if p.parent.is_dir() and p.parent != Path("."):
        return str(p.parent)
    return None


def collect_files(folder: str) -> list[str]:
    """Klasördeki (alt klasörlere girmeden) şifreli paket dosyalarını döndürür.
    .apkg uzantılı dosya varsa sadece onları, yoksa gizli olmayan tüm dosyaları alır."""
    try:
        items = sorted(
            (p for p in Path(folder).iterdir()
             if p.is_file() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except Exception:
        return []
    apkg = [p for p in items if p.suffix.lower() == ".apkg"]
    return [p.as_posix() for p in (apkg or items)]


def ghost_button(parent, text, command, width=100, height=36, accent=True, **kw):
    return ctk.CTkButton(
        parent,
        text=text,
        width=width,
        height=height,
        corner_radius=10,
        font=ctk.CTkFont(FONT, 13, "bold"),
        fg_color="transparent",
        border_width=1,
        border_color=ACCENT if accent else CARD_BORDER,
        hover_color=GHOST_HOVER,
        text_color=ACCENT if accent else TEXT,
        command=command,
        **kw,
    )


def styled_entry(parent, placeholder):
    return ctk.CTkEntry(
        parent,
        placeholder_text=placeholder,
        height=36,
        corner_radius=10,
        border_width=1,
        border_color=CARD_BORDER,
        fg_color=INPUT_BG,
        text_color=TEXT,
        placeholder_text_color=MUTED,
        font=ctk.CTkFont(FONT, 13),
    )


# ──────── Ayarlar penceresi ────────
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent: "DecryptorApp"):
        super().__init__(parent)
        self.parent = parent
        self.title("Ayarlar")
        self.configure(fg_color=BG)
        self.resizable(False, False)

        w, h = 540, 250
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

        self.transient(parent)
        self.after(150, self._grab)
        parent._apply_icon(self)

        self._build_ui()

    def _grab(self):
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="Ayarlar",
            font=ctk.CTkFont(FONT, 20, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(
            self,
            text="Altyazı gömme için FFmpeg gerekir.",
            font=ctk.CTkFont(FONT, 12),
            text_color=MUTED,
        ).pack(anchor="w", padx=24)

        card = ctk.CTkFrame(
            self,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        card.pack(fill="x", padx=24, pady=(14, 0))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="FFmpeg yolu (ffmpeg.exe)",
            font=ctk.CTkFont(FONT, 13, "bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 0))

        self.entry_ffmpeg = styled_entry(card, "ffmpeg.exe dosyasını seç…")
        self.entry_ffmpeg.grid(row=1, column=0, sticky="ew", padx=(16, 10), pady=(4, 14))
        self.entry_ffmpeg.insert(0, self.parent.ffmpeg_path)

        ghost_button(card, "Gözat", self._browse_ffmpeg, width=90).grid(
            row=1, column=1, padx=(0, 16), pady=(4, 14)
        )

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=(16, 0))

        ctk.CTkButton(
            btns,
            text="Kaydet",
            width=120,
            height=38,
            corner_radius=10,
            font=ctk.CTkFont(FONT, 13, "bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self._save,
        ).pack(side="right")
        ghost_button(
            btns, "İptal", self.destroy, width=90, height=38, accent=False
        ).pack(side="right", padx=(0, 10))

    def _browse_ffmpeg(self):
        # Mevcut yolun klasöründen aç; yoksa son bilinen ffmpeg klasöründen
        initial = (
            existing_dir(self.entry_ffmpeg.get().strip())
            or existing_dir(self.parent.config.get("ffmpeg_last_dir", ""))
            or str(Path.home())
        )
        path = filedialog.askopenfilename(
            title="ffmpeg.exe Seç",
            initialdir=initial,
            filetypes=[("Executable", "*.exe"), ("Tüm Dosyalar", "*.*")],
        )
        if path:
            self.entry_ffmpeg.delete(0, "end")
            self.entry_ffmpeg.insert(0, path)
            self.parent.config["ffmpeg_last_dir"] = str(Path(path).parent)

    def _save(self):
        self.parent.ffmpeg_path = self.entry_ffmpeg.get().strip() or "ffmpeg"
        self.parent._save_config()
        self.parent._log("Ayarlar kaydedildi.", "info")
        self.destroy()


# ──────── Ana pencere ────────
class DecryptorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        if sys.platform.startswith("win"):
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "mycompany.myproduct.subproduct.1"
                )
            except Exception:
                pass

        self.title("AIU Şifre Çözücü")
        self.geometry("660x720")
        self.minsize(600, 680)
        self.configure(fg_color=BG)
        self._apply_icon(self)

        self.service = PackageDecryptionService()
        self.ffmpeg_path = "ffmpeg"  # Varsayılan sistem yolu
        self.last_input_dir = ""     # Dosya seçici için bağımsız klasör hafızası
        self.config: dict = {}
        self._busy = False
        self._settings_win: SettingsWindow | None = None

        # Toplu seçim durumu
        self.selected_files: list[str] = []
        self._selection_label = ""   # Entry'de gösterilen "N dosya seçildi" metni

        self._build_ui()
        self._load_config()

    # ───── ikon ─────
    def _get_resource_path(self, relative_path: str) -> str:
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, relative_path)
        return str(app_dir() / relative_path)

    def _apply_icon(self, window):
        icon_path = self._get_resource_path("app_icon.ico")
        if not os.path.exists(icon_path):
            return

        def apply():
            try:
                window.iconbitmap(icon_path)
            except Exception:
                pass

        apply()
        # customtkinter, pencere açıldıktan sonra varsayılan ikonu geri koyabiliyor
        window.after(250, apply)

    # ───── arayüz ─────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # Başlık + ayarlar
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 6))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_box,
            text="AIU Şifre Çözücü",
            font=ctk.CTkFont(FONT, 26, "bold"),
            text_color=TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Şifreli bölüm dosyasını (veya birden fazlasını) ve hedef klasörü seç.",
            font=ctk.CTkFont(FONT, 13),
            text_color=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        ghost_button(
            header,
            "Ayarlar",
            self._open_settings,
            width=70,
            height=34,
            accent=False,
        ).grid(row=0, column=1, sticky="ne")

        # Dosya kartları
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", padx=28, pady=(16, 0))
        cards.grid_columnconfigure(0, weight=1)

        self.entry_file = self._path_card(
            cards, 0, "1", "Şifreli dosya(lar)",
            "Dosya(lar) seç, klasör seç veya yolu yapıştır…",
            [
                ("Dosya(lar)", self._select_encrypted_files),
                ("Klasör", self._select_input_folder),
            ],
        )
        self.entry_output = self._path_card(
            cards, 1, "2", "Hedef klasör",
            "Dosyaların çıkarılacağı klasör…",
            [("Klasör Seç", self._select_output_dir)],
        )

        # Seçenekler
        opt = ctk.CTkFrame(
            self,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        opt.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 0))
        self.chk_embed_subtitles = ctk.CTkCheckBox(
            opt,
            text="Altyazıları videoya göm (VTT altyazı dosyaları da saklanır)",
            font=ctk.CTkFont(FONT, 13),
            text_color=TEXT,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            border_color=MUTED,
            corner_radius=6,
            command=self._save_config,
        )
        self.chk_embed_subtitles.pack(anchor="w", padx=18, pady=14)

        # Aksiyon alanı
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=3, column=0, sticky="ew", padx=28, pady=(16, 0))
        action.grid_columnconfigure(0, weight=1)

        self.btn_decrypt = ctk.CTkButton(
            action,
            text="Dosyayı Çöz ve Çıkar",
            font=ctk.CTkFont(FONT, 15, "bold"),
            height=48,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            text_color_disabled="#C9C3F5",
            command=self._start_decryption,
        )
        self.btn_decrypt.grid(row=0, column=0, sticky="ew")

        ghost_button(
            action, "Klasörü Aç", self._open_output,
            width=120, height=48, accent=False,
        ).grid(row=0, column=1, padx=(10, 0))

        self.progress = ctk.CTkProgressBar(
            action,
            height=4,
            corner_radius=2,
            fg_color=CARD_BORDER,
            progress_color=ACCENT,
            mode="indeterminate",
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.progress.set(0)

        # Günlük
        log_card = ctk.CTkFrame(
            self,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        log_card.grid(row=4, column=0, sticky="nsew", padx=28, pady=(16, 0))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        log_head = ctk.CTkFrame(log_card, fg_color="transparent")
        log_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            log_head, text="Günlük",
            font=ctk.CTkFont(FONT, 13, "bold"), text_color=TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            log_head, text="Temizle", width=64, height=24, corner_radius=8,
            font=ctk.CTkFont(FONT, 12), fg_color="transparent",
            hover_color=GHOST_HOVER, text_color=MUTED, command=self._clear_log,
        ).pack(side="right")

        self.textbox_log = ctk.CTkTextbox(
            log_card,
            fg_color=INPUT_BG,
            corner_radius=10,
            font=ctk.CTkFont("Consolas", 12),
            text_color=TEXT,
            wrap="word",
            border_width=0,
        )
        self.textbox_log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 12))
        for tag, color in (
            ("ok", SUCCESS), ("err", ERROR), ("warn", WARN),
            ("info", MUTED), ("main", TEXT),
        ):
            self.textbox_log.tag_config(tag, foreground=color)
        self.textbox_log.configure(state="disabled")

        # Durum çubuğu
        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=5, column=0, sticky="ew", padx=28, pady=(8, 16))
        self.status_dot = ctk.CTkLabel(
            status, text="●", font=ctk.CTkFont(size=12), text_color=SUCCESS
        )
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(
            status, text="Hazır", font=ctk.CTkFont(FONT, 12), text_color=MUTED
        )
        self.status_label.pack(side="left", padx=(6, 0))

        self._log("Uygulama hazır.", "info")

    def _path_card(self, parent, row, step, title, placeholder, buttons):
        """buttons: [(metin, komut), ...] — kartın sağında yan yana dizilir."""
        card = ctk.CTkFrame(
            parent,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text=step, width=28, height=28, corner_radius=14,
            fg_color=ACCENT, text_color="white",
            font=ctk.CTkFont(FONT, 13, "bold"),
        ).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)

        ctk.CTkLabel(
            card, text=title, font=ctk.CTkFont(FONT, 13, "bold"),
            text_color=TEXT, anchor="w",
        ).grid(row=0, column=1, columnspan=2, sticky="w", pady=(14, 0))

        entry = styled_entry(card, placeholder)
        entry.grid(row=1, column=1, sticky="ew", pady=(4, 14))

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.grid(row=1, column=2, padx=(10, 16), pady=(4, 14))
        for i, (text, command) in enumerate(buttons):
            ghost_button(btn_box, text, command, width=90 if len(buttons) > 1 else 100).pack(
                side="left", padx=(0 if i == 0 else 8, 0)
            )
        return entry

    # ───── ayarlar / config ─────
    def _open_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsWindow(self)

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_input_dir = data.get("last_input_dir", "")

                    last_out = data.get("last_output_dir", "")
                    if last_out and os.path.exists(last_out):
                        self.entry_output.delete(0, "end")
                        self.entry_output.insert(0, last_out)

                    self.ffmpeg_path = data.get("ffmpeg_path", "ffmpeg")

                    if data.get("embed_subtitles", False):
                        self.chk_embed_subtitles.select()
            except Exception:
                pass

    def _save_config(self, *args):
        try:
            data = {
                "last_input_dir": self.last_input_dir,
                "last_output_dir": self.entry_output.get().strip(),
                "ffmpeg_path": self.ffmpeg_path,
                "embed_subtitles": bool(self.chk_embed_subtitles.get()),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ───── yardımcılar ─────
    def _log(self, text: str, tag: str = "main"):
        self.textbox_log.configure(state="normal")
        self.textbox_log.insert("end", text + "\n", tag)
        self.textbox_log.see("end")
        self.textbox_log.configure(state="disabled")

    def _log_safe(self, text: str, tag: str = "main"):
        self.after(0, lambda: self._log(text, tag))

    def _clear_log(self):
        self.textbox_log.configure(state="normal")
        self.textbox_log.delete("1.0", "end")
        self.textbox_log.configure(state="disabled")

    def _set_status(self, text: str, color: str):
        self.status_label.configure(text=text)
        self.status_dot.configure(text_color=color)

    def _set_status_safe(self, text: str, color: str):
        self.after(0, lambda: self._set_status(text, color))

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self.btn_decrypt.configure(state="disabled", text="İşleniyor…")
            self.progress.start()
            self._set_status("İşleniyor…", WARN)
        else:
            self.progress.stop()
            self.progress.set(0)
            self.btn_decrypt.configure(state="normal", text="Dosyayı Çöz ve Çıkar")

    def _open_output(self):
        out = self.entry_output.get().strip()
        if out and os.path.isdir(out):
            open_folder(out)
        else:
            self._log("[!] Açılacak geçerli bir hedef klasör yok.", "warn")

    # ───── seçiciler ─────
    def _set_selection(self, files: list[str]):
        """Seçilen dosyaları kaydeder, entry'yi ve varsayılan hedef klasörü günceller."""
        files = [Path(f).as_posix() for f in files]
        self.selected_files = files
        self.last_input_dir = Path(files[0]).parent.as_posix()

        self.entry_file.delete(0, "end")
        if len(files) == 1:
            self._selection_label = ""
            self.entry_file.insert(0, files[0])
        else:
            self._selection_label = f"{len(files)} dosya seçildi"
            self.entry_file.insert(0, self._selection_label)
            self._log(f"\n[+] {len(files)} dosya seçildi:", "info")
            for f in files:
                self._log(f"    • {Path(f).name}", "info")

        # Hedef dizin boşsa varsayılan öner
        if not self.entry_output.get().strip():
            first = Path(files[0])
            if len(files) == 1:
                default_dir = (first.parent / first.stem).as_posix()
            else:
                # Toplu işlemde her dosya kendi alt klasörüne çıkarılır
                default_dir = first.parent.as_posix()
            self.entry_output.delete(0, "end")
            self.entry_output.insert(0, default_dir)

        self._save_config()

    def _initial_input_dir(self) -> str:
        if self.last_input_dir and os.path.exists(self.last_input_dir):
            return self.last_input_dir
        return os.getcwd()

    def _select_encrypted_files(self):
        """Tek veya çoklu dosya seçimi (Ctrl / Shift ile)."""
        paths = filedialog.askopenfilenames(
            title="Şifreli Dosya(lar) Seç",
            initialdir=self._initial_input_dir(),
            filetypes=[("Tüm Dosyalar", "*.*"), ("APKG Dosyaları", "*.apkg")],
        )
        if paths:
            self._set_selection(list(paths))

    def _select_input_folder(self):
        """Klasördeki tüm şifreli dosyaları seç."""
        folder = filedialog.askdirectory(
            title="Şifreli Dosyaların Olduğu Klasörü Seç",
            initialdir=self._initial_input_dir(),
        )
        if not folder:
            return
        files = collect_files(folder)
        if not files:
            self._log(f"[!] Klasörde dosya bulunamadı: {folder}", "warn")
            return
        self._set_selection(files)

    def _select_output_dir(self):
        current_val = self.entry_output.get().strip()
        initial = current_val if (current_val and os.path.exists(current_val)) else os.getcwd()

        dir_path = filedialog.askdirectory(
            title="Hedef Klasör Seç", initialdir=initial
        )
        if dir_path:
            clean_dir = Path(dir_path).as_posix()
            self.entry_output.delete(0, "end")
            self.entry_output.insert(0, clean_dir)
            self._save_config()

    def _resolve_inputs(self) -> list[str]:
        """Entry'deki değeri işlenecek dosya listesine çevirir."""
        text = self.entry_file.get().strip().strip('"')
        if not text:
            return []

        # Butonlarla yapılan çoklu seçim
        if self.selected_files and text == self._selection_label:
            return [f for f in self.selected_files if os.path.isfile(f)]

        # Elle yazılan/yapıştırılan yol: klasör ya da dosya olabilir
        if os.path.isdir(text):
            return collect_files(text)
        if os.path.isfile(text):
            return [Path(text).as_posix()]
        return []

    # ───── iş akışı ─────
    def _start_decryption(self):
        if self._busy:
            return

        files = self._resolve_inputs()
        output_dir = self.entry_output.get().strip()

        if not files:
            self._log("[-] Hata: Lütfen geçerli bir şifreli dosya veya klasör seçin!", "err")
            self._set_status("Geçersiz dosya", ERROR)
            return

        if not output_dir:
            self._log("[-] Hata: Lütfen geçerli bir hedef dizin seçin!", "err")
            self._set_status("Hedef klasör eksik", ERROR)
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as ex:
            self._log(f"[-] Hedef klasör oluşturulamadı: {ex}", "err")
            self._set_status("Hedef klasör hatası", ERROR)
            return

        self.last_input_dir = str(Path(files[0]).parent)
        self._save_config()

        # Arayüz değerlerini ana thread'de oku, arka plana parametre olarak ver
        embed = bool(self.chk_embed_subtitles.get())
        ffmpeg = self.ffmpeg_path

        self._set_busy(True)
        threading.Thread(
            target=self._run_async_decrypt,
            args=(files, output_dir, embed, ffmpeg),
            daemon=True,
        ).start()

    def _run_async_decrypt(self, files, output_dir, embed, ffmpeg):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ok = False
        msg = "Hata oluştu"
        try:
            ok, msg = loop.run_until_complete(
                self._async_batch_process(files, output_dir, embed, ffmpeg)
            )
        except Exception as ex:
            self._log_safe(f"[-] Beklenmeyen hata: {ex}", "err")
        finally:
            loop.close()
            self.after(0, lambda: self._finish(ok, msg))

    def _finish(self, ok: bool, msg: str):
        self._set_busy(False)
        self._set_status(msg, SUCCESS if ok else ERROR)

    async def _async_batch_process(self, files, output_dir, embed, ffmpeg):
        total = len(files)
        batch = total > 1
        succeeded = 0
        failed: list[str] = []

        for i, file_path in enumerate(files, start=1):
            name = Path(file_path).name
            if batch:
                self._set_status_safe(f"İşleniyor… ({i}/{total})", WARN)
                self._log_safe(f"\n━━ [{i}/{total}] {name} ━━", "info")
                # Her dosya kendi alt klasörüne çıkarılır
                target_dir = (Path(output_dir) / Path(file_path).stem).as_posix()
            else:
                target_dir = output_dir

            if await self._process_one(file_path, target_dir, embed, ffmpeg):
                succeeded += 1
            else:
                failed.append(name)

        if batch:
            if failed:
                self._log_safe(
                    f"\n[!] Toplu işlem bitti: {succeeded}/{total} başarılı. "
                    f"Sorunlu dosyalar: {', '.join(failed)}",
                    "warn",
                )
            else:
                self._log_safe(f"\n[✓] Toplu işlem tamamlandı: {total}/{total} dosya.", "ok")

        ok = not failed
        if ok:
            return True, "Tamamlandı"
        return False, f"{len(failed)} dosyada hata" if batch else "Hata oluştu"

    async def _process_one(self, file_path: str, output_dir: str, embed: bool, ffmpeg: str) -> bool:
        try:
            file_name = Path(file_path).stem
            self.after(0, lambda: self._log(f"\n[+] '{file_name}' işleniyor..."))

            # Yol ayracını normalize et (Windows'ta \ ve / karışmasın)
            output_dir = Path(output_dir).as_posix()

            # Ana hedef klasör + altyazılar alt klasörü
            os.makedirs(output_dir, exist_ok=True)
            subtitles_dir = os.path.join(output_dir, "altyazilar")
            os.makedirs(subtitles_dir, exist_ok=True)

            result = await self.service.decrypt_episode_async(file_path)

            # 1. Altyazıları 'altyazilar' alt klasörüne kopyala (.vtt)
            saved_subs = []
            for sub in result.subtitle_files:
                if os.path.exists(sub.path):
                    target_sub = os.path.join(
                        subtitles_dir, f"{file_name}_{sub.language}.vtt"
                    )
                    shutil.copyfile(sub.path, target_sub)

                    # FFmpeg'in yeni altyazı yolunu bulması için güncelliyoruz
                    sub.path = target_sub
                    saved_subs.append(sub)

                    self.after(
                        0,
                        lambda s=target_sub: self._log(
                            f" -> Altyazı çıkarıldı: altyazilar/{Path(s).name}"
                        ),
                    )

            # 2. Videoyu çıkar (.mp4)
            target_video = None
            if result.video_path and os.path.exists(result.video_path):
                target_video = os.path.join(output_dir, f"{file_name}_raw.mp4")
                shutil.move(result.video_path, target_video)
                self._log_safe(f"  → Video çıkarıldı: {Path(target_video).name}", "info")

            all_ok = True

            # 3. Seçiliyse FFmpeg ile videoya göm (.mkv)
            if embed and target_video and saved_subs:
                self.after(
                    0,
                    lambda: self._log(" -> FFmpeg ile altyazılar birleştiriliyor..."),
                )
                output_mkv = os.path.join(output_dir, f"{file_name}_altyazili.mkv")

                success, err_details = await self.service.embed_subtitles_async(
                    target_video, saved_subs, output_mkv, ffmpeg
                )

                if success:
                    self.after(
                        0,
                        lambda: self._log(
                            f" [✓] Gömülü MKV oluşturuldu: {Path(output_mkv).name}"
                        ),
                    )
                else:
                    all_ok = False
                    self.after(
                        0,
                        lambda err=err_details: self._log(
                            f" [-] FFmpeg Hatası: {err}"
                        ),
                    )

            if all_ok:
                self._log_safe(
                    f"[✓] '{file_name}' tamamlandı! Çıktı dizini: '{output_dir}'", "ok"
                )
            else:
                self._log_safe(
                    f"[!] '{file_name}' çıkarıldı ancak altyazı gömme başarısız oldu.", "warn"
                )
            return all_ok

        except Exception as ex:
            self._log_safe(f"[-] Çözme hatası ({Path(file_path).name}): {ex}", "err")
            return False


if __name__ == "__main__":
    app = DecryptorApp()
    app.mainloop()