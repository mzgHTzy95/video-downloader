import os
import sys
import threading
import time
import tempfile
import shutil
import zipfile
import subprocess
import requests
import yt_dlp
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
from queue import Queue
from packaging import version
from PIL import Image, ImageTk


class DownloadTask:
    def __init__(self, url, quality, path, ui):
        self.url = url
        self.quality = quality
        self.path = path
        self.ui = ui  # UI dict for this task
        self.thread = None
        self.cancel_flag = False
        self.pause_flag = False


class VideoDownloader:
    VERSION = "2.0.1"
    GITHUB_REPO = "yourusername/repository-name"

    def __init__(self, root):
        self.root = root
        icon_path = self.get_icon_path()
        if icon_path and os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except Exception:
                pass

        self.tasks = []
        self.download_queue = Queue()

        self.set_windows_taskbar_icon()
        self.root.title(f"Video Downloader v{self.VERSION}")
        self.root.geometry("750x700")
        self.root.configure(bg="#F9F9F9")

        # Variables
        self.download_path = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.url_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="best")
        self.is_playlist = tk.BooleanVar(value=False)

        # used by legacy single-download UI (kept but not required)
        self.progress_content = None

        self.setup_ui()
        # optional: self.check_for_updates()

    def get_icon_path(self):
        if getattr(sys, "frozen", False):
            base_path = getattr(
                sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
            )
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "youtube.ico")
        return icon_path if os.path.exists(icon_path) else None

    def set_windows_taskbar_icon(self):
        try:
            if sys.platform == "win32":
                myappid = "com.Videodownloader.app.1.0.0"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    def setup_ui(self):
        self.colors = {
            "primary": "#FF0000",
            "primary_dark": "#CC0000",
            "background": "#F9F9F9",
            "card": "#FFFFFF",
            "text_primary": "#212121",
            "text_secondary": "#757575",
            "accent": "#00C853",
            "border": "#E0E0E0",
        }

        # Scrollable area
        main_canvas = tk.Canvas(
            self.root, highlightthickness=0, bg=self.colors["background"]
        )
        scrollbar = ttk.Scrollbar(
            self.root, orient="vertical", command=main_canvas.yview
        )
        scrollable_frame = ttk.Frame(main_canvas)

        scrollable_frame.bind(
            "<Configure>", lambda e: self._on_frame_configure(main_canvas)
        )
        canvas_window = main_canvas.create_window(
            (0, 0), window=scrollable_frame, anchor="nw"
        )
        self.main_canvas = main_canvas

        def on_canvas_configure(event):
            main_canvas.itemconfig(canvas_window, width=event.width)

        main_canvas.bind("<Configure>", on_canvas_configure)
        main_canvas.configure(yscrollcommand=scrollbar.set)
        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            if event.num == 5 or getattr(event, "delta", 0) < 0:
                main_canvas.yview_scroll(1, "units")
            elif event.num == 4 or getattr(event, "delta", 0) > 0:
                main_canvas.yview_scroll(-1, "units")

        main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        main_canvas.bind_all("<Button-4>", _on_mousewheel)
        main_canvas.bind_all("<Button-5>", _on_mousewheel)

        main_frame = tk.Frame(scrollable_frame, bg=self.colors["background"])
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = tk.Frame(main_frame, bg=self.colors["primary"], height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="🎬 Video Downloader",
            font=("Segoe UI", 22, "bold"),
            bg=self.colors["primary"],
            fg="#FFFFFF",
        )
        title_label.pack(pady=20)

        container_frame = tk.Frame(main_frame, bg=self.colors["background"])
        container_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # === LEFT SIDEBAR ===
        self.sidebar = tk.Frame(
            container_frame,
            width=300,
            bg=self.colors["card"],
            highlightbackground=self.colors["border"],
            # highlightthickness=1
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

        # Sidebar internal padding
        self.sidebar_inner = tk.Frame(self.sidebar, bg=self.colors["card"])
        self.sidebar_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Thumbnail placeholder
        self.thumbnail_label = tk.Label(
            self.sidebar_inner,
            text="Thumbnail will\nappear here",
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
            font=("Segoe UI", 10),
            justify="center",
            relief=tk.FLAT,
            bd=0,
            width=28,
            height=10,
        )
        self.thumbnail_label.pack(fill=tk.X, pady=(0, 12))
        self.thumbnail_label.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )

        # Video title in sidebar
        self.sidebar_title = tk.Label(
            self.sidebar_inner,
            text="Title will appear here",
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
            font=("Segoe UI", 10, "bold"),
            wraplength=260,
            justify="left",
        )
        self.sidebar_title.pack(fill=tk.X, pady=(0, 12))

        # small metadata labels
        self.sidebar_meta = tk.Label(
            self.sidebar_inner,
            text="Duration: --\nChannel: --",
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
            font=("Segoe UI", 9),
            justify="left",
        )
        self.sidebar_meta.pack(fill=tk.X, pady=(0, 12))

        content_frame = tk.Frame(container_frame, bg=self.colors["background"])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # URL input card
        url_card = tk.Frame(content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0)
        url_card.pack(fill=tk.X, pady=(0, 15))
        url_card.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )
        url_card_inner = tk.Frame(url_card, bg=self.colors["card"])
        url_card_inner.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(
            url_card_inner,
            text="🔗 Paste Video or Playlist URL",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
        ).pack(anchor=tk.W, pady=(0, 8))

        url_input_frame = tk.Frame(url_card_inner, bg=self.colors["card"])
        url_input_frame.pack(fill=tk.X, pady=(0, 10))

        self.url_entry = tk.Entry(
            url_input_frame,
            textvariable=self.url_var,
            font=("Segoe UI", 10),
            bg="#F5F5F5",
            fg=self.colors["text_primary"],
            relief=tk.FLAT,
            bd=0,
            insertbackground=self.colors["primary"],
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, ipadx=10)

        fetch_btn = tk.Button(
            url_input_frame,
            text="Fetch Preview",
            command=self.fetch_preview_threaded,
            font=("Segoe UI", 10),
            bg="#E0E0E0",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=6,
        )
        fetch_btn.pack(side=tk.LEFT, padx=(8, 0))

        playlist_frame = tk.Frame(url_card_inner, bg=self.colors["card"])
        playlist_frame.pack(fill=tk.X)
        tk.Checkbutton(
            playlist_frame,
            text="Download entire playlist",
            variable=self.is_playlist,
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
            activebackground=self.colors["card"],
            selectcolor=self.colors["card"],
            relief=tk.FLAT,
            bd=0,
        ).pack(anchor=tk.W)

        # quality card
        quality_card = tk.Frame(
            content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0
        )
        quality_card.pack(fill=tk.X, pady=(0, 15))
        quality_card.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )
        quality_inner = tk.Frame(quality_card, bg=self.colors["card"])
        quality_inner.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(
            quality_inner,
            text="🎯 Select Quality",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
        ).pack(anchor=tk.W, pady=(0, 10))

        quality_options_frame = tk.Frame(quality_inner, bg=self.colors["card"])
        quality_options_frame.pack(fill=tk.X)

        qualities = [
            ("🏆 Best", "best"),
            ("1080p", "1080"),
            ("720p", "720"),
            ("480p", "480"),
            ("🎵 Audio", "audio"),
        ]

        for text, value in qualities:
            tk.Radiobutton(
                quality_options_frame,
                text=text,
                variable=self.quality_var,
                value=value,
                font=("Segoe UI", 10),
                relief=tk.FLAT,
                bd=0,
            ).pack(side=tk.LEFT, padx=(0, 20))

        # path card
        path_card = tk.Frame(
            self.sidebar_inner, bg=self.colors["card"], relief=tk.FLAT, bd=0
        )
        path_card.pack(fill=tk.X, pady=(0, 15))
        path_card.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )
        path_inner = tk.Frame(path_card, bg=self.colors["card"])
        path_inner.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(
            path_inner,
            text="📁 Download Location",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
        ).pack(anchor=tk.W, pady=(0, 8))

        path_input_frame = tk.Frame(path_inner, bg=self.colors["card"])
        path_input_frame.pack(fill=tk.X)

        path_entry = tk.Entry(
            path_input_frame,
            textvariable=self.download_path,
            font=("Segoe UI", 9),
            bg="#FAFAFA",
            fg=self.colors["text_secondary"],
            relief=tk.FLAT,
            bd=0,
            state="readonly",
        )
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, ipadx=10)

        browse_btn = tk.Button(
            path_input_frame,
            text="Browse",
            command=self.browse_folder,
            font=("Segoe UI", 9, "bold"),
            bg="#F5F5F5",
            fg=self.colors["text_primary"],
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground="#E0E0E0",
        )
        browse_btn.pack(side=tk.LEFT, padx=(10, 0), ipady=8, ipadx=15)

        # progress parent card (title + inner where per-download cards will be placed)
        self.progress_content = tk.Frame(
            content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0
        )
        self.progress_content.pack(fill=tk.X, pady=(0, 15))
        self.progress_content.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )

        header_frame = tk.Frame(self.progress_content, bg=self.colors["card"])
        header_frame.pack(fill=tk.X, padx=15, pady=(12, 5))

        tk.Label(
            header_frame,
            text="📥 Download Progress",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X)

        inner = tk.Frame(self.progress_content, bg=self.colors["card"])
        inner.pack(fill=tk.X, padx=15, pady=15)

        # Container to hold per-download UI cards (inside main content area)
        self.downloads_container = tk.Frame(content_frame, bg=self.colors["background"])
        self.downloads_container.pack(fill=tk.BOTH, expand=False, pady=(10, 0))

        # Action Buttons
        buttons_frame = tk.Frame(content_frame, bg=self.colors["background"])
        buttons_frame.pack(fill=tk.X, pady=(5, 0))

        self.download_btn = tk.Button(
            buttons_frame,
            text="⬇ Download Now",
            command=self.start_download,
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["primary"],
            fg="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground=self.colors["primary_dark"],
            activeforeground="#FFFFFF",
        )
        self.download_btn.pack(fill=tk.X, ipady=15)

        self.update_btn = tk.Button(
            buttons_frame,
            text="Check for Updates",
            command=self.manual_update_check,
            font=("Segoe UI", 9),
            bg=self.colors["background"],
            fg=self.colors["text_secondary"],
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground=self.colors["background"],
        )
        self.update_btn.pack(pady=(10, 0))

        scrollable_frame.columnconfigure(0, weight=1)
        scrollable_frame.rowconfigure(0, weight=1)

    # ---------------------------
    # Thumbnail / preview functions
    # ---------------------------

    def fetch_preview_threaded(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a URL to fetch preview")
            return
        # Run fetch in background thread to avoid blocking UI
        t = threading.Thread(target=self.load_preview, args=(url,), daemon=True)
        t.start()

    def load_preview(self, url):
        """Fetch title, thumbnail, channel, duration using yt-dlp and requests in background."""
        # default text while loading
        self.root.after(0, lambda: self.sidebar_title.config(text="Loading preview..."))
        self.root.after(
            0,
            lambda: self.thumbnail_label.config(
                text="Loading thumbnail", image="", compound="center"
            ),
        )

        try:
            ydl_opts = {"quiet": True, "nocheckcertificate": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            title = info.get("title", "Unknown")
            duration = info.get("duration")
            duration_text = "--"
            if isinstance(duration, (int, float)):
                m, s = divmod(int(duration), 60)
                h, m = divmod(m, 60)
                duration_text = f"{h:d}h {m:d}m {s:d}s" if h else f"{m:d}m {s:d}s"
            channel = info.get("uploader") or info.get("channel") or "Unknown"
            thumbnail_url = info.get("thumbnail")

            # schedule metadata update
            meta_text = f"Duration: {duration_text}\nChannel: {channel}"
            self.root.after(0, lambda: self.sidebar_title.config(text=title))
            self.root.after(0, lambda: self.sidebar_meta.config(text=meta_text))

            # load thumbnail image (Pillow required)
            if thumbnail_url and Image and ImageTk:
                try:
                    r = requests.get(thumbnail_url, timeout=8)
                    r.raise_for_status()
                    from io import BytesIO

                    img = Image.open(BytesIO(r.content))
                    # keep aspect, limit to sidebar width
                    img.thumbnail((280, 180), Image.ANTIALIAS)
                    self.thumbnail_img = ImageTk.PhotoImage(img)
                    self.root.after(
                        0,
                        lambda: self.thumbnail_label.config(
                            image=self.thumbnail_img, text=""
                        ),
                    )
                except Exception:
                    self.root.after(
                        0,
                        lambda: self.thumbnail_label.config(
                            text="Thumbnail not available", image=""
                        ),
                    )
            else:
                # no pillow or no thumbnail
                self.root.after(
                    0,
                    lambda: self.thumbnail_label.config(
                        text="Thumbnail not available", image=""
                    ),
                )
        except Exception as e:
            # show failure
            self.root.after(
                0, lambda: self.sidebar_title.config(text="Preview not available")
            )
            self.root.after(0, lambda: self.sidebar_meta.config(text=""))
            self.root.after(
                0,
                lambda: self.thumbnail_label.config(
                    text="Thumbnail not available", image=""
                ),
            )

    def _on_frame_configure(self, canvas):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(1.0)

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path.get())
        if folder:
            self.download_path.set(folder)

    def ensure_ffmpeg(self):
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return None
        except Exception:
            pass

        local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        ffmpeg_root = os.path.join(local_appdata, "VideoDownloader", "ffmpeg")
        ffmpeg_bin = ffmpeg_root
        ffmpeg_exe = os.path.join(ffmpeg_bin, "ffmpeg.exe")
        ffprobe_exe = os.path.join(ffmpeg_bin, "ffprobe.exe")

        if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
            return ffmpeg_bin

        os.makedirs(ffmpeg_bin, exist_ok=True)
        try:
            self.root.after(0, lambda: None)  # safe no-op scheduled on main thread
        except Exception:
            pass

        ffmpeg_zip_url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
        tmp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(tmp_dir, "ffmpeg.zip")

        try:
            with requests.get(ffmpeg_zip_url, stream=True, timeout=20) as r:
                r.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            f.write(chunk)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            found_ffmpeg = None
            found_ffprobe = None
            for root_dir, dirs, files in os.walk(tmp_dir):
                if "ffmpeg.exe" in files:
                    found_ffmpeg = os.path.join(root_dir, "ffmpeg.exe")
                if "ffprobe.exe" in files:
                    found_ffprobe = os.path.join(root_dir, "ffprobe.exe")
                if found_ffmpeg and found_ffprobe:
                    break

            if not found_ffmpeg or not found_ffprobe:
                raise RuntimeError("FFmpeg binaries not found in downloaded archive.")

            shutil.copy2(found_ffmpeg, ffmpeg_exe)
            shutil.copy2(found_ffprobe, ffprobe_exe)

            try:
                self.root.after(0, lambda: None)
            except Exception:
                pass

            return ffmpeg_bin
        except Exception as e:
            messagebox.showerror(
                "FFmpeg Required",
                f"FFmpeg is required but could not be downloaded automatically.\n\nPlease install FFmpeg and ensure it's on PATH.\n\nError:\n{str(e)}",
            )
            return None
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    def create_download_card_ui(self, video_title="Downloading..."):
        parent = self.progress_content

        card = tk.Frame(parent, bg=self.colors["card"], bd=0)
        card.pack(fill=tk.X, padx=10, pady=10)
        card.configure(highlightbackground=self.colors["border"], highlightthickness=1)

        inner = tk.Frame(card, bg=self.colors["card"])
        inner.pack(fill=tk.X, padx=12, pady=12)

        header = tk.Frame(inner, bg=self.colors["card"])
        header.pack(fill=tk.X)

        title_label = tk.Label(
            header,
            text=video_title,
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
            anchor="w",
        )
        title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        percent_label = tk.Label(
            header,
            text="0%",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["primary"],
        )
        percent_label.pack(side=tk.RIGHT)

        # size_label = tk.Label(
        #     header,
        #     text="",
        #     font=("Segoe UI", 9),
        #     bg=self.colors["card"],
        #     fg=self.colors["text_secondary"],
        # )
        # size_label.pack(side=tk.RIGHT, padx=(0, 10))

        progress_bg = tk.Frame(inner, bg="#F0F0F0", height=8)
        progress_bg.pack(fill=tk.X, pady=(8, 10))

        progress_canvas = tk.Canvas(
            progress_bg, bg="#F0F0F0", height=8, highlightthickness=0
        )
        progress_canvas.pack(fill=tk.BOTH, expand=True)
        progress_bar = progress_canvas.create_rectangle(
            0, 0, 0, 8, fill=self.colors["primary"], outline=""
        )

        stats_frame = tk.Frame(inner, bg=self.colors["card"])
        stats_frame.pack(fill=tk.X)

        speed_label = tk.Label(
            stats_frame,
            text="Speed: --",
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
        )
        speed_label.pack(side=tk.LEFT)

        status_label = tk.Label(
            stats_frame,
            text="Ready",
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
        )
        status_label.pack(side=tk.RIGHT)

        btn_frame = tk.Frame(inner, bg=self.colors["card"])
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        pause_btn = tk.Button(
            btn_frame,
            text="Pause",
            bg="#fff176",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            width=10,
        )
        pause_btn.pack(side=tk.LEFT, padx=(0, 6))

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            bg="#F44336",
            fg="white",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            width=10,
        )
        cancel_btn.pack(side=tk.LEFT)

        ui = {
            "card": card,
            "title": title_label,
            "percent": percent_label,
            # "size": size_label,
            "progress_canvas": progress_canvas,
            "progress_bar": progress_bar,
            "speed": speed_label,
            "status": status_label,
            "btn_frame": btn_frame,
            "pause": pause_btn,
            "cancel": cancel_btn,
        }
        return ui

    def toggle_pause_task(self, task):
        # schedule UI update on main thread
        def do_toggle():
            if task.pause_flag:
                task.pause_flag = False
                try:
                    task.ui["pause"].config(text="Pause")
                    task.ui["status"].config(text="Resuming...")
                except Exception:
                    pass
            else:
                task.pause_flag = True
                try:
                    task.ui["pause"].config(text="Resume")
                    task.ui["status"].config(text="Paused")
                except Exception:
                    pass

        self.root.after(0, do_toggle)

    def cancel_task(self, task):
        task.cancel_flag = True

        def do_cancel():
            try:
                task.ui["status"].config(text="Cancelling...")
                task.ui["cancel"].config(state=tk.DISABLED)
                task.ui["pause"].config(state=tk.DISABLED)
            except Exception:
                pass

        self.root.after(0, do_cancel)

    def make_progress_hook(self, task):
        """
        Returns a function suitable for yt-dlp progress_hooks.
        It schedules UI updates on the main thread via root.after.
        If task.pause_flag is True, it will sleep inside the hook (pausing the download thread).
        """

        def hook(d):
            if task.cancel_flag:
                # Raise to abort download inside yt-dlp
                raise Exception("Cancelled")

            # If paused, block here until resumed or cancelled
            while task.pause_flag and not task.cancel_flag:
                # schedule a UI update to show paused state
                try:
                    self.root.after(0, lambda: task.ui["status"].config(text="Paused"))
                except Exception:
                    pass
                time.sleep(0.25)

            if task.cancel_flag:
                raise Exception("Cancelled")

            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0)
                percent = (downloaded * 100 / total) if total else 0.0

                # format sizes
                def format_bytes(b):
                    if b >= 1024**3:
                        return f"{round(b / (1024 ** 3))} GB"
                    if b >= 1024**2:
                        return f"{round(b / (1024 ** 2))} MB"
                    if b >= 1024:
                        return f"{round(b / 1024)} KB"
                    return f"{b} B"

                downloaded_str = format_bytes(downloaded) if downloaded else ""
                total_str = format_bytes(total) if total else ""
                size_text = (
                    f"{downloaded_str} / {total_str}" if total else downloaded_str
                )

                speed = d.get("speed", 0)
                if speed:
                    if speed > 1024 * 1024:
                        speed_text = f"⚡ {speed / (1024 * 1024):.2f} MB/s"
                    else:
                        speed_text = f"⚡ {speed / 1024:.1f} KB/s"
                else:
                    speed_text = "Speed: ---"

                # schedule UI update
                def ui_update():
                    try:
                        task.ui["percent"].config(text=f"{percent:.0f}%")
                        task.ui["size"].config(text=size_text)
                        task.ui["speed"].config(text=speed_text)
                        task.ui["status"].config(text=size_text)
                        # update canvas bar width
                        canvas = task.ui["progress_canvas"]
                        width = max(canvas.winfo_width(), 2)
                        new_width = (width * percent) / 100.0
                        canvas.coords(task.ui["progress_bar"], 0, 0, new_width, 8)
                    except Exception:
                        pass

                self.root.after(0, ui_update)

            elif status == "finished":

                def ui_finished():
                    try:
                        task.ui["percent"].config(text="100%")
                        task.ui["status"].config(text="Processing...")
                        canvas = task.ui["progress_canvas"]
                        width = max(canvas.winfo_width(), 2)
                        canvas.coords(task.ui["progress_bar"], 0, 0, width, 8)
                    except Exception:
                        pass

                self.root.after(0, ui_finished)

        return hook

    def run_task(self, task: DownloadTask):
        url = task.url
        quality = task.quality
        download_path = task.path

        # Ensure ffmpeg
        ffmpeg_dir = None
        try:
            ffmpeg_dir = self.ensure_ffmpeg()
        except Exception:
            ffmpeg_dir = None

        ydl_opts = {
            "outtmpl": os.path.join(download_path, "%(title)s.%(ext)s"),
            "progress_hooks": [self.make_progress_hook(task)],
            "merge_output_format": "mp4",
        }

        if ffmpeg_dir:
            ydl_opts["ffmpeg_location"] = ffmpeg_dir

        # Format handling
        if quality == "audio":
            ydl_opts.update(
                {
                    "format": "bestaudio/best",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
        elif quality == "best":
            ydl_opts["format"] = (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            )
        else:
            # numeric like '720', '480'
            try:
                h = int(str(quality).replace("p", ""))
                ydl_opts["format"] = (
                    f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best"
                )
            except Exception:
                ydl_opts["format"] = "best"

        try:
            # Try to extract info to get title and update card title
            try:
                with yt_dlp.YoutubeDL({}) as ydl_info:
                    info = ydl_info.extract_info(url, download=False)
                    title = info.get("title") or url
                    # schedule title update
                    self.root.after(0, lambda: task.ui["title"].config(text=title))
            except Exception:
                pass

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            def ui_on_complete():
                try:
                    task.ui["status"].config(text="Completed", fg=self.colors["accent"])
                    task.ui["progress_canvas"].pack_forget()
                    task.ui["progress_bar"].pack_forget()
                    task.ui["speed"].pack_forget()
                    task.ui["pause"].pack_forget()
                    task.ui["cancel"].pack_forget()
                    task.ui["btn_frame"].pack_forget()
                except Exception:
                    pass

            self.root.after(0, ui_on_complete)
        except Exception as e:

            def ui_on_fail():
                try:
                    if task.cancel_flag:
                        task.ui["status"].config(text="Cancelled", fg="#FF9800")
                    else:
                        task.ui["status"].config(text=f"Failed: {str(e)}", fg="#F44336")
                    task.ui["pause"].config(state=tk.DISABLED)
                    task.ui["cancel"].config(state=tk.DISABLED)
                except Exception:
                    pass

            self.root.after(0, ui_on_fail)

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a URL")
            return

        ui = self.create_download_card_ui()

        task = DownloadTask(
            url=url,
            quality=self.quality_var.get(),
            path=self.download_path.get(),
            ui=ui,
        )

        ui["cancel"].config(command=lambda t=task: self.cancel_task(t))
        ui["pause"].config(command=lambda t=task: self.toggle_pause_task(t))

        task.thread = threading.Thread(
            target=lambda t=task: self.run_task(t), args=(task,), daemon=True
        )
        # Note: above lambda with args duplicates; simpler start thread with target=self.run_task, args=(task,)
        task.thread = threading.Thread(target=self.run_task, args=(task,), daemon=True)
        task.thread.start()

        self.tasks.append(task)

    # minimal update check wrapper (safe)
    def check_for_updates(self, auto=True):
        try:
            response = requests.get(
                f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest",
                timeout=5,
            )
            if response.status_code == 200:
                latest_release = response.json()
                latest_version = latest_release["tag_name"].lstrip("v")
                if version.parse(latest_version) > version.parse(self.VERSION):
                    if messagebox.askyesno(
                        "Update Available",
                        f"New version {latest_version} is available. Open release page?",
                    ):
                        import webbrowser

                        webbrowser.open(latest_release.get("html_url"))
        except Exception:
            pass

    def manual_update_check(self):
        self.check_for_updates(auto=False)


def main():
    root = tk.Tk()
    app = VideoDownloader(root)
    root.mainloop()


if __name__ == "__main__":
    main()
