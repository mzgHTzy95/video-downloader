import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Toplevel
import yt_dlp
import threading
import os
import requests
import json
from packaging import version
import subprocess
import sys
from PIL import Image, ImageTk
from io import BytesIO
from datetime import datetime
import zipfile
import shutil
import tempfile
import ctypes
from queue import Queue
from collections import OrderedDict


class VideoDownloader:
    VERSION = "1.0.0"  # Current app version
    GITHUB_REPO = "yourusername/repository-name"
    MAX_CONCURRENT_DOWNLOADS = 3  # Maximum parallel downloads

    def __init__(self, root):
        self.root = root
        # Set window icon for title bar and taskbar
        icon_path = self.get_icon_path()
        if icon_path and os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except:
                pass

        # Set taskbar icon on Windows (for grouped taskbar items)
        self.set_windows_taskbar_icon()
        self.root.title(f"Video Downloader v{self.VERSION}")
        self.root.geometry("600x700")
        self.root.resizable(True, True)
        self.root.configure(bg="#F9F9F9")

        # Variables
        self.download_path = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.url_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="best")
        self.is_playlist = tk.BooleanVar(value=False)
        self.is_downloading = False
        self.is_fetching_preview = False
        self.video_info = None
        self.thumbnail_label = None
        self.download_thread = None
        self.cancel_download = False

        # Playlist tracking variables
        self.playlist_total = 0
        self.playlist_current = 0
        self.playlist_completed = 0
        self.current_video_title = ""

        # Playlist selection variables
        self.playlist_videos = []  # List of video info dicts
        self.selected_videos = []  # List of selected video indices
        self.playlist_checkboxes = {}  # Dict of video_id: checkbox_var

        # Parallel download management
        self.download_queue = Queue()
        self.active_downloads = []  # List of active download threads
        self.download_slots = []  # UI slots for showing parallel downloads
        self.completed_count = 0

        # Dynamic quality options
        self.available_qualities = []  # Will be populated after fetching video info
        self.quality_buttons = []  # References to quality radio buttons

        self.setup_ui()
        self.check_for_updates()

    def get_icon_path(self):
        """Get the path to the icon file (works for both script and exe)"""
        if getattr(sys, "frozen", False):
            # Running as compiled executable
            base_path = getattr(
                sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
            )
        else:
            # Running as script
            base_path = os.path.dirname(os.path.abspath(__file__))

        icon_path = os.path.join(base_path, "youtube.ico")
        return icon_path if os.path.exists(icon_path) else None

    def set_windows_taskbar_icon(self):
        """Set the taskbar icon on Windows to prevent Python default icon"""
        try:
            if sys.platform == "win32":
                # Set AppUserModelID to ensure proper taskbar icon grouping
                myappid = "com.Videodownloader.app.1.0.0"  # arbitrary string
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass  # Ignore errors on non-Windows platforms

    def setup_ui(self):
        # Configure modern color scheme
        self.colors = {
            "primary": "#FF0000",  # YouTube red
            "primary_dark": "#CC0000",
            "background": "#F9F9F9",
            "card": "#FFFFFF",
            "text_primary": "#212121",
            "text_secondary": "#757575",
            "accent": "#00C853",  # Success green
            "border": "#E0E0E0",
        }

        # Create canvas and scrollbar for scrollable main window
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

        # Store canvas reference for auto-scroll
        self.main_canvas = main_canvas

        # Bind canvas width to scrollable frame width
        def on_canvas_configure(event):
            main_canvas.itemconfig(canvas_window, width=event.width)

        main_canvas.bind("<Configure>", on_canvas_configure)
        main_canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind mousewheel scrolling
        def _on_mousewheel(event):
            if event.num == 5 or event.delta < 0:
                main_canvas.yview_scroll(1, "units")
            elif event.num == 4 or event.delta > 0:
                main_canvas.yview_scroll(-1, "units")

        main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        main_canvas.bind_all("<Button-4>", _on_mousewheel)
        main_canvas.bind_all("<Button-5>", _on_mousewheel)

        # Main container
        main_frame = tk.Frame(scrollable_frame, bg=self.colors["background"])
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Section with gradient-like effect
        header_frame = tk.Frame(main_frame, bg=self.colors["primary"], height=80)
        header_frame.pack(fill=tk.X, pady=(0, 0))
        header_frame.pack_propagate(False)

        # App Title in Header
        title_label = tk.Label(
            header_frame,
            text="🎬 Video Downloader",
            font=("Segoe UI", 22, "bold"),
            bg=self.colors["primary"],
            fg="#FFFFFF",
        )
        title_label.pack(pady=20)

        # Content container with padding
        content_frame = tk.Frame(main_frame, bg=self.colors["background"])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # URL Input Card
        url_card = tk.Frame(content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0)
        url_card.pack(fill=tk.X, pady=(0, 15))

        # Add subtle shadow effect with border
        url_card.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )

        url_card_inner = tk.Frame(url_card, bg=self.colors["card"])
        url_card_inner.pack(fill=tk.X, padx=15, pady=15)

        # URL Label
        tk.Label(
            url_card_inner,
            text="📎 Paste Video or Playlist URL",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
        ).pack(anchor=tk.W, pady=(0, 8))

        # URL Entry Frame
        url_input_frame = tk.Frame(url_card_inner, bg=self.colors["card"])
        url_input_frame.pack(fill=tk.X, pady=(0, 10))

        # Styled URL Entry
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

        # Playlist Checkbox with modern style
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

        # Quality Selection Card
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

        for i, (text, value) in enumerate(qualities):
            tk.Radiobutton(
                quality_options_frame,
                text=text,
                variable=self.quality_var,
                value=value,
                font=("Segoe UI", 10),
                relief=tk.FLAT,
                bd=0,
            ).pack(side=tk.LEFT, padx=(0, 20))

        # Download Path Card
        path_card = tk.Frame(
            content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0
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

        # Progress Card
        progress_card = tk.Frame(
            content_frame, bg=self.colors["card"], relief=tk.FLAT, bd=0
        )
        progress_card.pack(fill=tk.X, pady=(0, 15))
        progress_card.configure(
            highlightbackground=self.colors["border"], highlightthickness=1
        )

        progress_inner = tk.Frame(progress_card, bg=self.colors["card"])
        progress_inner.pack(fill=tk.X, padx=15, pady=15)

        # Progress header
        progress_header = tk.Frame(progress_inner, bg=self.colors["card"])
        progress_header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            progress_header,
            text="📊 Download Progress",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["text_primary"],
        ).pack(side=tk.LEFT)

        self.percent_label = tk.Label(
            progress_header,
            text="0%",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["card"],
            fg=self.colors["primary"],
        )
        self.percent_label.pack(side=tk.RIGHT)

        # File size label (next to percentage)
        self.size_label = tk.Label(
            progress_header,
            text="",
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
        )
        self.size_label.pack(side=tk.RIGHT, padx=(0, 10))

        # Progress Bar with custom style
        progress_bg = tk.Frame(progress_inner, bg="#F0F0F0", height=8)
        progress_bg.pack(fill=tk.X, pady=(0, 10))

        self.progress_canvas = tk.Canvas(
            progress_bg, bg="#F0F0F0", height=8, highlightthickness=0
        )
        self.progress_canvas.pack(fill=tk.BOTH, expand=True)
        self.progress_bar = self.progress_canvas.create_rectangle(
            0, 0, 0, 8, fill=self.colors["primary"], outline=""
        )

        # Store for progress tracking
        self.progress = {"value": 0}

        # Stats Frame
        stats_frame = tk.Frame(progress_inner, bg=self.colors["card"])
        stats_frame.pack(fill=tk.X)

        self.speed_label = tk.Label(
            stats_frame,
            text="Speed: --",
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
        )
        self.speed_label.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            stats_frame,
            text="Ready to download",
            font=("Segoe UI", 9),
            bg=self.colors["card"],
            fg=self.colors["text_secondary"],
        )
        self.status_label.pack(side=tk.RIGHT)

        # Playlist progress label (hidden by default)
        self.playlist_label = tk.Label(
            progress_inner,
            text="",
            font=("Segoe UI", 9, "bold"),
            bg=self.colors["card"],
            fg=self.colors["primary"],
        )
        # Will be packed when playlist download starts

        # Action Buttons
        buttons_frame = tk.Frame(content_frame, bg=self.colors["background"])
        buttons_frame.pack(fill=tk.X, pady=(5, 0))

        # Download Button - Large and prominent
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

        # Cancel Button - Hidden by default
        self.cancel_btn = tk.Button(
            buttons_frame,
            text="✖ Cancel Download",
            command=self.cancel_download_action,
            font=("Segoe UI", 10, "bold"),
            bg="#F44336",
            fg="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground="#D32F2F",
            activeforeground="#FFFFFF",
        )
        # Cancel button starts hidden

        # Update Button - Smaller, secondary
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

        # Configure grid weights
        scrollable_frame.columnconfigure(0, weight=1)
        scrollable_frame.rowconfigure(0, weight=1)

    def _on_frame_configure(self, canvas):
        """Update scroll region and auto-scroll to bottom if content grows"""
        canvas.configure(scrollregion=canvas.bbox("all"))
        # Auto-scroll to bottom when new content is added
        canvas.yview_moveto(1.0)

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path.get())
        if folder:
            self.download_path.set(folder)

    def ensure_ffmpeg(self):
        """
        Ensure FFmpeg is available.
        """
        # Try system ffmpeg first
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return None  # Available on PATH
        except Exception:
            pass

        # Target install dir: %LOCALAPPDATA%\VideoDownloader\ffmpeg
        local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        ffmpeg_root = os.path.join(local_appdata, "VideoDownloader", "ffmpeg")
        ffmpeg_bin = ffmpeg_root  # we will store exe files directly here
        ffmpeg_exe = os.path.join(ffmpeg_bin, "ffmpeg.exe")
        ffprobe_exe = os.path.join(ffmpeg_bin, "ffprobe.exe")

        # If already downloaded, use it
        if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
            return ffmpeg_bin

        # Create directories
        os.makedirs(ffmpeg_bin, exist_ok=True)

        # Notify user
        try:
            self.status_label.config(
                text="Downloading FFmpeg (first run)...", fg="#FF9800"
            )
            self.root.update_idletasks()
        except Exception:
            pass

        # Download static build zip from yt-dlp FFmpeg builds
        # 64-bit Windows GPL build contains ffmpeg.exe and ffprobe.exe
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

            # Extract and locate bin folder
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            # Find ffmpeg.exe and ffprobe.exe inside extracted tree
            found_ffmpeg = None
            found_ffprobe = None
            for root, dirs, files in os.walk(tmp_dir):
                if "ffmpeg.exe" in files:
                    found_ffmpeg = os.path.join(root, "ffmpeg.exe")
                if "ffprobe.exe" in files:
                    found_ffprobe = os.path.join(root, "ffprobe.exe")
                if found_ffmpeg and found_ffprobe:
                    break

            if not found_ffmpeg or not found_ffprobe:
                raise RuntimeError("FFmpeg binaries not found in downloaded archive.")

            # Copy binaries into ffmpeg_bin
            shutil.copy2(found_ffmpeg, ffmpeg_exe)
            shutil.copy2(found_ffprobe, ffprobe_exe)

            try:
                self.status_label.config(
                    text="FFmpeg ready", fg=self.colors.get("accent", "#00C853")
                )
                self.root.update_idletasks()
            except Exception:
                pass

            return ffmpeg_bin

        except Exception as e:
            # If download failed, guide user to system-wide install
            messagebox.showerror(
                "FFmpeg Required",
                f"FFmpeg is required but could not be downloaded automatically.\n\n"
                f"Please install FFmpeg and ensure it's on PATH.\n\nError:\n{str(e)}",
            )
            return None
        finally:
            # Cleanup temp dir
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    def cancel_download_action(self):
        """Cancel the current download"""
        if self.is_downloading:
            self.cancel_download = True
            self.status_label.config(text="Cancelling download...", fg="#FF9800")
            self.download_btn.config(
                state=tk.NORMAL, text="⬇ Download Now", bg=self.colors["primary"]
            )
            self.cancel_btn.pack_forget()
            messagebox.showinfo("Cancelled", "Download has been cancelled.")
            self.status_label.config(
                text="Ready to download", fg=self.colors["text_secondary"]
            )
            self.percent_label.config(text="0%")
            self.speed_label.config(text="Speed: --", fg=self.colors["text_secondary"])

    def fetch_video_preview(self):
        """Fetch and display video preview information - REMOVED"""
        pass

    def _fetch_preview_thread(self, url):
        """Thread function to fetch video info - REMOVED"""
        pass

    def _show_loading_state(self):
        """Show loading state in preview section - REMOVED"""
        pass

    def _display_preview(self, video_info, thumbnail_image):
        """Display video preview information - REMOVED"""
        pass

    def _hide_preview(self):
        """Hide preview section - REMOVED"""
        pass

    def progress_hook(self, d):
        # Check if download was cancelled
        if self.cancel_download:
            raise Exception("Download cancelled by user")

        if d["status"] == "downloading":
            try:
                # Update progress percentage
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0)

                if total > 0:
                    percent = (downloaded * 100) / total
                    self.progress["value"] = percent

                    # Update canvas progress bar
                    canvas_width = self.progress_canvas.winfo_width()
                    if canvas_width > 1:
                        bar_width = (canvas_width * percent) / 100
                        self.progress_canvas.coords(
                            self.progress_bar, 0, 0, bar_width, 8
                        )

                    self.percent_label.config(text=f"{percent:.0f}%")

                    # Update file size display
                    def format_bytes(bytes_val):
                        if bytes_val >= 1024 * 1024 * 1024:
                            return f"{round(bytes_val / (1024**3))} GB"
                        elif bytes_val >= 1024 * 1024:
                            return f"{round(bytes_val / (1024**2))} MB"
                        elif bytes_val >= 1024:
                            return f"{round(bytes_val / 1024)} KB"
                        else:
                            return f"{bytes_val} B"

                    downloaded_str = format_bytes(downloaded)
                    total_str = format_bytes(total)
                    self.size_label.config(text=f"{downloaded_str} / {total_str}")
                else:
                    self.progress["value"] = 0
                    self.percent_label.config(text="---%")
                    self.size_label.config(text="")

                # Calculate and display speed
                speed = d.get("speed", 0)
                if speed:
                    if speed > 1024 * 1024:  # MB/s
                        speed_text = f"⚡ {speed/(1024*1024):.1f} MB/s"
                    else:  # KB/s
                        speed_text = f"⚡ {speed/1024:.1f} KB/s"
                else:
                    speed_text = "Speed: ---"
                self.speed_label.config(text=speed_text, fg=self.colors["accent"])

                # Calculate and show ETA
                eta = d.get("eta", None)
                if eta is not None:
                    minutes = eta // 60
                    seconds = eta % 60
                    if minutes > 0:
                        eta_text = f"Time remaining: {minutes}m {seconds}s"
                    else:
                        eta_text = f"Time remaining: {seconds}s"
                else:
                    eta_text = "Calculating..."

                # Show playlist progress if downloading playlist
                if self.playlist_total > 1:
                    status_text = f"{eta_text} | Video {self.playlist_current}/{self.playlist_total}"
                else:
                    status_text = eta_text

                self.status_label.config(text=status_text, fg=self.colors["primary"])
                self.root.update_idletasks()
            except Exception as e:
                if "cancelled" not in str(e).lower():
                    print(f"Progress update error: {str(e)}")
                raise

        elif d["status"] == "finished":
            self.progress["value"] = 100
            canvas_width = self.progress_canvas.winfo_width()
            if canvas_width > 1:
                self.progress_canvas.coords(self.progress_bar, 0, 0, canvas_width, 8)
            self.percent_label.config(text="100%")
            self.speed_label.config(text="Speed: --", fg=self.colors["text_secondary"])

            # Update playlist completion counter
            if self.playlist_total > 1:
                self.playlist_completed += 1
                self.status_label.config(
                    text=f"Processing... {self.playlist_completed}/{self.playlist_total} completed",
                    fg="#FF9800",
                )
            else:
                self.status_label.config(text="Processing... Please wait", fg="#FF9800")
            self.root.update_idletasks()

    def download_video(self):
        url = self.url_var.get().strip()
        quality = self.quality_var.get()
        download_path = self.download_path.get()
        is_playlist = self.is_playlist.get()

        if not url:
            messagebox.showerror("Error", "Please enter a Video URL")
            return

        try:
            # Ensure FFmpeg availability (auto-download if missing)
            ffmpeg_dir = self.ensure_ffmpeg()

            # Configure yt-dlp options
            ydl_opts = {
                "outtmpl": os.path.join(download_path, "%(title)s.%(ext)s"),
                "progress_hooks": [self.progress_hook],
                "merge_output_format": "mp4",  # Ensure proper merging of video and audio
                "postprocessor_args": [
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                ],  # Preserve quality during merge
            }

            # If we downloaded ffmpeg locally, point yt-dlp to it
            if ffmpeg_dir:
                ydl_opts["ffmpeg_location"] = ffmpeg_dir

            # Handle playlist downloads
            if is_playlist:
                ydl_opts["noplaylist"] = False
                ydl_opts["outtmpl"] = os.path.join(
                    download_path, "%(playlist)s/%(playlist_index)s - %(title)s.%(ext)s"
                )
            else:
                ydl_opts["noplaylist"] = True

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
                # Fix: Ensure both video and audio are downloaded and merged
                ydl_opts["format"] = (
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                )
            else:
                # Fix: Ensure audio is included for specific quality selections
                ydl_opts["format"] = (
                    f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
                )

            # Download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore
                info = ydl.extract_info(url, download=False)

                # Initialize playlist tracking
                if is_playlist and "entries" in info:
                    entries = list(info["entries"])
                    self.playlist_total = len(entries)
                    self.playlist_current = 0
                    self.playlist_completed = 0

                    # Show playlist progress label
                    self.playlist_label.pack(fill=tk.X, pady=(5, 0))
                    self.playlist_label.config(
                        text=f"📂 Playlist: {info.get('title', 'Unknown')} ({self.playlist_total} videos)"
                    )
                    self.root.update_idletasks()

                    # Auto-scroll to show playlist label
                    self.main_canvas.yview_moveto(1.0)

                    # Download each video in playlist
                    for idx, entry in enumerate(entries, 1):
                        if self.cancel_download:
                            break

                        self.playlist_current = idx
                        video_title = entry.get("title", "Unknown")

                        # Update playlist status
                        self.playlist_label.config(
                            text=f"📂 Downloading video {idx}/{self.playlist_total}: {video_title[:50]}..."
                        )
                        self.root.update_idletasks()

                        # Auto-scroll to show current progress
                        self.main_canvas.yview_moveto(1.0)

                        # Download individual video
                        try:
                            ydl.download(
                                [entry.get("url") or entry.get("webpage_url") or url]
                            )
                        except Exception as e:
                            print(f"Error downloading video {idx}: {str(e)}")
                            continue

                    # Final playlist status
                    if not self.cancel_download:
                        self.playlist_label.config(
                            text=f"✅ Playlist complete: {self.playlist_completed}/{self.playlist_total} videos downloaded"
                        )
                else:
                    # Single video download
                    self.playlist_total = 1
                    self.playlist_current = 1
                    self.playlist_completed = 0
                    ydl.download([url])

            self.progress["value"] = 100
            canvas_width = self.progress_canvas.winfo_width()
            if canvas_width > 1:
                self.progress_canvas.coords(self.progress_bar, 0, 0, canvas_width, 8)

            if is_playlist:
                success_msg = f"Playlist downloaded successfully!\n{self.playlist_completed} of {self.playlist_total} videos completed."
            else:
                success_msg = "Video downloaded successfully!"

            self.status_label.config(
                text="Download completed!", fg=self.colors["accent"]
            )
            messagebox.showinfo("Success", success_msg)
            self.percent_label.config(text="0%")
            self.status_label.config(
                text="Ready to download",
                fg=self.colors["text_secondary"],
            )

        except Exception as e:
            if self.cancel_download:
                self.status_label.config(text="Download cancelled", fg="#FF9800")
                if self.playlist_total > 1:
                    self.playlist_label.config(
                        text=f"⚠️ Cancelled: {self.playlist_completed}/{self.playlist_total} videos completed"
                    )
            else:
                self.status_label.config(text=f"Error: {str(e)}", fg="#F44336")
                messagebox.showerror("Error", f"Download failed: {str(e)}")

        finally:
            self.is_downloading = False
            self.cancel_download = False
            self.download_btn.config(
                state=tk.NORMAL, text="⬇ Download Now", bg=self.colors["primary"]
            )
            self.cancel_btn.pack_forget()
            self.progress["value"] = 0
            self.progress_canvas.coords(self.progress_bar, 0, 0, 0, 8)
            self.size_label.config(text="")

            # Reset playlist tracking
            self.playlist_total = 0
            self.playlist_current = 0
            self.playlist_completed = 0

            # Hide playlist label after a delay
            if hasattr(self, "playlist_label"):
                self.root.after(5000, lambda: self.playlist_label.pack_forget())

    def start_download(self):
        if self.is_downloading:
            return

        self.is_downloading = True
        self.cancel_download = False
        self.download_btn.config(
            state=tk.DISABLED, text="⏳ Downloading...", bg="#9E9E9E"
        )
        self.url_entry.config(textvariable="")
        # Show cancel button
        self.cancel_btn.pack(fill=tk.X, ipady=12, pady=(10, 0))

        self.progress["value"] = 0
        self.progress_canvas.coords(self.progress_bar, 0, 0, 0, 8)
        self.percent_label.config(text="0%")
        self.size_label.config(text="")
        self.status_label.config(text="Starting download...", fg=self.colors["primary"])

        # Run download in separate thread
        self.download_thread = threading.Thread(target=self.download_video, daemon=True)
        self.download_thread.start()

    def check_for_updates(self, auto=True):
        """Check for updates from GitHub releases"""
        try:
            response = requests.get(
                f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest",
                timeout=5,
            )
            if response.status_code == 200:
                latest_release = response.json()
                latest_version = latest_release["tag_name"].lstrip("v")

                if version.parse(latest_version) > version.parse(self.VERSION):
                    update_msg = f"New version {latest_version} is available!\n\nCurrent version: {self.VERSION}\n\nWould you like to download the update?"
                    if messagebox.askyesno("Update Available", update_msg):
                        self.download_update(latest_release)
                elif not auto:
                    messagebox.showinfo(
                        "No Updates",
                        f"You are using the latest version ({self.VERSION})",
                    )
        except Exception as e:
            if not auto:
                messagebox.showerror(
                    "Update Check Failed", f"Could not check for updates:\n{str(e)}"
                )

    def manual_update_check(self):
        """Manual update check triggered by button"""
        self.check_for_updates(auto=False)

    def download_update(self, release_info):
        """Download and install update"""
        try:
            # Find the appropriate asset (e.g., .exe for Windows)
            assets = release_info.get("assets", [])
            download_url = None

            for asset in assets:
                if asset["name"].endswith(".exe") or asset["name"].endswith(".zip"):
                    download_url = asset["browser_download_url"]
                    break

            if not download_url:
                # If no binary found, redirect to release page
                download_url = release_info["html_url"]
                messagebox.showinfo(
                    "Manual Download Required",
                    f"Please download the update manually from:\n{download_url}",
                )
                import webbrowser

                webbrowser.open(download_url)
            else:
                # Download the update
                messagebox.showinfo(
                    "Downloading Update",
                    "The update will be downloaded. Please install it after download completes.",
                )
                import webbrowser

                webbrowser.open(download_url)

        except Exception as e:
            messagebox.showerror(
                "Update Failed", f"Failed to download update:\n{str(e)}"
            )


def main():
    root = tk.Tk()
    app = VideoDownloader(root)
    root.mainloop()


if __name__ == "__main__":
    main()
