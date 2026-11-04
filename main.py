#Pydroid run kivy
import io
import os
from PIL import Image as PILImage, ImageDraw, ImageOps
from openpyxl import load_workbook
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape

# Optional PyMuPDF support if installed
try:
    import fitz
    HAS_FITZ = True
except Exception:
    HAS_FITZ = False

# Compatible with pypdf and all PyPDF2 versions in Pydroid 3
try:
    from PyPDF2 import PdfReader, PdfWriter
except ImportError:
    from PyPDF2 import PdfFileReader as PdfReader, PdfFileWriter as PdfWriter

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import platform
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.image import Image as KivyImage
from kivy.uix.filechooser import FileChooserListView

Window.clearcolor = (0.07, 0.08, 0.11, 1)
Window.softinput_mode = "below_target"

ANDROID_ROOT = "/storage/emulated/0"


def request_android_permissions():
    if platform == "android":
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
            ])
        except Exception:
            pass


def get_default_storage():
    if os.path.exists(ANDROID_ROOT) and os.access(ANDROID_ROOT, os.R_OK):
        return ANDROID_ROOT
    return os.path.abspath(".")


def get_safe_output_path(folder, custom_name, default_name):
    name = custom_name.strip() if custom_name else ""
    if not name:
        name = default_name
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    out_path = os.path.join(folder, name)
    if not os.path.exists(out_path):
        return out_path
    base, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = os.path.join(folder, f"{base}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def get_pdf_pages(reader):
    return reader.pages if hasattr(reader, "pages") else [reader.getPage(i) for i in range(reader.getNumPages())]


def add_pdf_page(writer, page):
    if hasattr(writer, "add_page"):
        writer.add_page(page)
    else:
        writer.addPage(page)


def rotate_pdf_page_obj(page, angle):
    if angle % 360 == 0:
        return page
    if hasattr(page, "rotate"):
        return page.rotate(angle)
    page.rotateClockwise(angle)
    return page


# ---------------- Data Model & Live Thumbnail Renderer ----------------
class PageItem:
    """Represents a single interactive page (from a PDF or Image) in the workspace."""

    def __init__(self, source_type, file_path, page_index=0, rotation=0, pre_extracted_text=""):
        self.source_type = source_type  # 'pdf' or 'image'
        self.file_path = file_path
        self.page_index = page_index
        self.rotation = rotation % 360
        self.short_name = os.path.basename(file_path)
        self.extracted_text = pre_extracted_text
        self._base_pil = None
        self._build_base_preview()

    def _build_base_preview(self):
        thumb_w, thumb_h = 240, 320
        if self.source_type == "image":
            try:
                with PILImage.open(self.file_path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    canvas_img = PILImage.new("RGB", (thumb_w, thumb_h), (248, 250, 252))
                    im_copy = im.copy()
                    im_copy.thumbnail((thumb_w - 16, thumb_h - 16))
                    ox = (thumb_w - im_copy.width) // 2
                    oy = (thumb_h - im_copy.height) // 2
                    canvas_img.paste(im_copy, (ox, oy))
                    self._base_pil = canvas_img
                    self.extracted_text = f"[Image Page]\nFile: {self.short_name}\nSize: {im.width}x{im.height} px"
                    return
            except Exception as e:
                self.extracted_text = f"Image error: {e}"

        # Option A: If PyMuPDF (fitz) is installed, rasterize exact PDF page
        if self.source_type == "pdf" and HAS_FITZ:
            try:
                doc = fitz.open(self.file_path)
                page = doc.load_page(self.page_index)
                if not self.extracted_text:
                    self.extracted_text = page.get_text("text") or ""
                pix = page.get_pixmap(dpi=65)
                mode = "RGBA" if pix.alpha else "RGB"
                im = PILImage.frombytes(mode, [pix.width, pix.height], pix.samples).convert("RGB")
                im.thumbnail((thumb_w, thumb_h))
                self._base_pil = im
                doc.close()
                return
            except Exception:
                pass

        # Option B: Pure-Python Pillow visual page preview (100% Pydroid & APK compatible)
        canvas_img = PILImage.new("RGB", (thumb_w, thumb_h), (252, 253, 255))
        draw = ImageDraw.Draw(canvas_img)
        draw.rectangle([0, 0, thumb_w - 1, thumb_h - 1], outline=(180, 190, 210), width=2)
        draw.rectangle([0, 0, thumb_w - 1, 26], fill=(38, 72, 145))
        header_txt = f"{self.short_name[:16]} - P.{self.page_index + 1}"
        draw.text((8, 6), header_txt, fill=(255, 255, 255))

        y_cursor = 36
        if self.extracted_text:
            lines = [ln.strip() for ln in self.extracted_text.splitlines() if ln.strip()]
            for ln in lines[:16]:
                safe_ln = ln.encode("ascii", "ignore").decode("ascii")[:32]
                draw.text((10, y_cursor), safe_ln, fill=(40, 50, 68))
                y_cursor += 16
                if y_cursor > thumb_h - 18:
                    break
        else:
            for ry in range(y_cursor + 12, thumb_h - 28, 18):
                draw.line([(16, ry), (thumb_w - 20, ry)], fill=(215, 222, 232), width=3)
            draw.text((34, thumb_h // 2), f"PDF Page #{self.page_index + 1}", fill=(95, 110, 135))

        self._base_pil = canvas_img

    def get_rotated_pil(self):
        if self._base_pil is None:
            self._build_base_preview()
        if self.rotation % 360 == 0:
            return self._base_pil
        return self._base_pil.rotate(-self.rotation, expand=True)

    def get_kivy_texture(self):
        pil_im = self.get_rotated_pil()
        bio = io.BytesIO()
        pil_im.save(bio, format="PNG")
        bio.seek(0)
        return CoreImage(bio, ext="png").texture


# ---------------- Styled UI Components ----------------
class RoundedCard(BoxLayout):
    def __init__(self, bg_color=(0.14, 0.16, 0.22, 1), radius=10, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.radius = radius
        with self.canvas.before:
            self.card_color = Color(*self.bg_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(self.radius)])
        self.bind(pos=self._update_rect, size=self._update_rect)

    def set_bg(self, rgba):
        self.bg_color = rgba
        self.card_color.rgba = rgba

    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size


class ModernButton(Button):
    def __init__(self, bg_color=(0.24, 0.47, 0.96, 1), radius=7, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.bg_color = bg_color
        self.color = (1, 1, 1, 1)
        self.bold = True
        self.font_size = kwargs.get("font_size", "12sp")
        with self.canvas.before:
            self.btn_color = Color(*self.bg_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._update_rect, size=self._update_rect, state=self._update_state)

    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def _update_state(self, instance, value):
        if value == "down":
            self.btn_color.rgba = [max(0, c - 0.14) for c in self.bg_color[:3]] + [1]
        else:
            self.btn_color.rgba = self.bg_color


# ---------------- Draggable Interactive Page Card ----------------
class PageCard(RoundedCard):
    """Visual card for a single page supporting drag-and-drop, rotate, delete, and insert-after."""

    def __init__(self, workspace, page_item, index, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(260),
            padding=dp(6),
            spacing=dp(4),
            bg_color=(0.14, 0.17, 0.24, 1),
            radius=10,
            **kwargs,
        )
        self.workspace = workspace
        self.page_item = page_item
        self.index = index
        self.is_selected = False

        with self.canvas.after:
            self.border_color = Color(0.28, 0.56, 1, 0)
            self.border_line = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)),
                width=dp(1.8),
            )
        self.bind(pos=self._update_border, size=self._update_border)

        # Top Bar: Page Number Badge + Drag Handle + Delete Button
        top_bar = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(4))
        self.num_badge = ModernButton(
            text=f"#{index + 1}",
            size_hint_x=None,
            width=dp(38),
            bg_color=(0.22, 0.45, 0.88, 1),
            font_size="11.5sp",
        )
        self.num_badge.bind(on_release=lambda *a: self.workspace.select_card(self.index))

        self.drag_handle = ModernButton(
            text=":: Hold & Drag ::",
            bg_color=(0.24, 0.28, 0.38, 1),
            font_size="11sp",
        )

        del_btn = ModernButton(
            text="X",
            size_hint_x=None,
            width=dp(30),
            bg_color=(0.78, 0.24, 0.28, 1),
            font_size="11.5sp",
        )
        del_btn.bind(on_release=lambda *a: self.workspace.delete_page_at(self.index))

        top_bar.add_widget(self.num_badge)
        top_bar.add_widget(self.drag_handle)
        top_bar.add_widget(del_btn)
        self.add_widget(top_bar)

        # Middle: Live Visual Thumbnail Image
        img_box = RoundedCard(bg_color=(0.09, 0.11, 0.15, 1), radius=6, padding=dp(3))
        self.thumb_img = KivyImage(
            texture=self.page_item.get_kivy_texture(),
            allow_stretch=True,
            keep_ratio=True,
        )
        img_box.add_widget(self.thumb_img)
        self.add_widget(img_box)

        # Source Subtitle
        tag = "IMG" if page_item.source_type == "image" else f"P.{page_item.page_index + 1}"
        rot_txt = f" ({page_item.rotation} deg)" if page_item.rotation else ""
        self.info_lbl = Label(
            text=f"[{tag}]{rot_txt} {page_item.short_name}",
            size_hint_y=None,
            height=dp(18),
            font_size="10.5sp",
            color=(0.75, 0.82, 0.94, 1),
            shorten=True,
            halign="center",
            valign="middle",
        )
        self.info_lbl.bind(size=self.info_lbl.setter("text_size"))
        self.add_widget(self.info_lbl)

        # Bottom Action Row: Move Left | Rotate 90 | View | +Here | Move Right
        act_bar = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(4))

        left_btn = ModernButton(text="<<", bg_color=(0.22, 0.26, 0.35, 1), font_size="11sp")
        left_btn.bind(on_release=lambda *a: self.workspace.move_page(self.index, self.index - 1))

        rot_btn = ModernButton(text="Rot", bg_color=(0.48, 0.32, 0.78, 1), font_size="10.5sp")
        rot_btn.bind(on_release=lambda *a: self.workspace.rotate_page_at(self.index))

        zoom_btn = ModernButton(text="View", bg_color=(0.18, 0.52, 0.65, 1), font_size="10.5sp")
        zoom_btn.bind(on_release=lambda *a: self.workspace.open_zoom_preview(self.index))

        ins_btn = ModernButton(text="+Here", bg_color=(0.18, 0.6, 0.4, 1), font_size="10.5sp")
        ins_btn.bind(on_release=lambda *a: self.workspace.prompt_insert_at(self.index + 1))

        right_btn = ModernButton(text=">>", bg_color=(0.22, 0.26, 0.35, 1), font_size="11sp")
        right_btn.bind(on_release=lambda *a: self.workspace.move_page(self.index, self.index + 1))

        act_bar.add_widget(left_btn)
        act_bar.add_widget(rot_btn)
        act_bar.add_widget(zoom_btn)
        act_bar.add_widget(ins_btn)
        act_bar.add_widget(right_btn)
        self.add_widget(act_bar)

    def _update_border(self, *args):
        if self.width > 0 and self.height > 0:
            self.border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))

    def set_selected(self, selected, dragging=False):
        self.is_selected = selected
        if dragging:
            self.border_color.rgba = (1, 0.78, 0.2, 1)
            self.set_bg((0.22, 0.25, 0.35, 1))
        elif selected:
            self.border_color.rgba = (0.28, 0.62, 1, 1)
            self.set_bg((0.18, 0.22, 0.32, 1))
        else:
            self.border_color.rgba = (0, 0, 0, 0)
            self.set_bg((0.14, 0.17, 0.24, 1))

    def refresh_visuals(self, new_index):
        self.index = new_index
        self.num_badge.text = f"#{new_index + 1}"
        tag = "IMG" if self.page_item.source_type == "image" else f"P.{self.page_item.page_index + 1}"
        rot_txt = f" ({self.page_item.rotation} deg)" if self.page_item.rotation else ""
        self.info_lbl.text = f"[{tag}]{rot_txt} {self.page_item.short_name}"
        self.thumb_img.texture = self.page_item.get_kivy_texture()

    def on_touch_down(self, touch):
        if self.drag_handle.collide_point(*touch.pos):
            self.workspace.select_card(self.index)
            self.workspace.start_card_drag(self, touch)
            return True
        if self.thumb_img.collide_point(*touch.pos):
            self.workspace.select_card(self.index)
        return super().on_touch_down(touch)


# ---------------- Full-Screen Zoom & Inspect Popup ----------------
class PageZoomPopup(Popup):
    def __init__(self, workspace, index, **kwargs):
        super().__init__(**kwargs)
        self.workspace = workspace
        self.index = index
        self.size_hint = (0.95, 0.92)
        self.background_color = (0.09, 0.11, 0.15, 1)
        self.separator_color = (0.24, 0.47, 0.96, 1)
        self.title_size = "15sp"

        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))

        self.preview_img = KivyImage(allow_stretch=True, keep_ratio=True, size_hint_y=0.62)
        root.add_widget(self.preview_img)

        self.text_box = TextInput(
            readonly=True,
            size_hint_y=0.26,
            background_color=(0.13, 0.15, 0.2, 1),
            foreground_color=(0.88, 0.92, 1, 1),
            font_size="12sp",
        )
        root.add_widget(self.text_box)

        ctrl = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        prev_btn = ModernButton(text="< Prev", bg_color=(0.24, 0.28, 0.38, 1))
        prev_btn.bind(on_release=lambda *a: self.step_page(-1))

        rot_btn = ModernButton(text="Rotate 90", bg_color=(0.48, 0.32, 0.78, 1))
        rot_btn.bind(on_release=self.rotate_current)

        del_btn = ModernButton(text="Delete", bg_color=(0.78, 0.24, 0.28, 1))
        del_btn.bind(on_release=self.delete_current)

        next_btn = ModernButton(text="Next >", bg_color=(0.24, 0.28, 0.38, 1))
        next_btn.bind(on_release=lambda *a: self.step_page(1))

        close_btn = ModernButton(text="Done", bg_color=(0.16, 0.62, 0.4, 1))
        close_btn.bind(on_release=self.dismiss)

        ctrl.add_widget(prev_btn)
        ctrl.add_widget(rot_btn)
        ctrl.add_widget(del_btn)
        ctrl.add_widget(next_btn)
        ctrl.add_widget(close_btn)
        root.add_widget(ctrl)

        self.content = root
        self.load_page_view()

    def load_page_view(self):
        if not self.workspace.pages or self.index >= len(self.workspace.pages):
            self.dismiss()
            return
        item = self.workspace.pages[self.index]
        self.title = f"Page #{self.index + 1} of {len(self.workspace.pages)} - {item.short_name}"
        self.preview_img.texture = item.get_kivy_texture()
        txt = item.extracted_text or "(No extractable text on this page)"
        self.text_box.text = f"--- Page Text Content ---\n{txt}"

    def step_page(self, delta):
        new_idx = self.index + delta
        if 0 <= new_idx < len(self.workspace.pages):
            self.index = new_idx
            self.workspace.select_card(new_idx)
            self.load_page_view()

    def rotate_current(self, *args):
        self.workspace.rotate_page_at(self.index)
        self.load_page_view()

    def delete_current(self, *args):
        self.workspace.delete_page_at(self.index)
        if not self.workspace.pages:
            self.dismiss()
        else:
            self.index = min(self.index, len(self.workspace.pages) - 1)
            self.load_page_view()


# ---------------- File Picker Popup ----------------
class FilePickerPopup(Popup):
    def __init__(self, title, filters, on_files_chosen, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.title_size = "15sp"
        self.size_hint = (0.96, 0.94)
        self.background_color = (0.1, 0.12, 0.16, 1)
        self.separator_color = (0.24, 0.47, 0.96, 1)
        self.on_files_chosen = on_files_chosen
        self.selected_files = []

        root = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))

        jump_bar = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(5))
        for lbl, sp in [("Up", ".."), ("Internal", ""), ("Download", "Download"), ("Documents", "Documents")]:
            b = ModernButton(text=lbl, bg_color=(0.22, 0.26, 0.34, 1))
            b.bind(on_release=lambda btn, s=sp: self.jump_folder(s))
            jump_bar.add_widget(b)
        root.add_widget(jump_bar)

        start_dir = get_default_storage()
        self.path_lbl = Label(
            text=start_dir,
            size_hint_y=None,
            height=dp(20),
            font_size="11sp",
            color=(0.68, 0.76, 0.88, 1),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="left",
        )
        self.path_lbl.bind(size=self.path_lbl.setter("text_size"))
        root.add_widget(self.path_lbl)

        self.fc = FileChooserListView(path=start_dir, filters=filters, multiselect=True)
        self.fc.bind(path=lambda inst, val: setattr(self.path_lbl, "text", val), selection=self._on_sel)
        root.add_widget(self.fc)

        self.sel_lbl = Label(
            text="Selected (0): Tap one or more files",
            size_hint_y=None,
            height=dp(26),
            font_size="11.5sp",
            color=(0.55, 0.9, 0.68, 1),
            halign="left",
            valign="middle",
            shorten=True,
        )
        self.sel_lbl.bind(size=self.sel_lbl.setter("text_size"))
        root.add_widget(self.sel_lbl)

        bot = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        cancel_btn = ModernButton(text="Cancel", bg_color=(0.28, 0.3, 0.38, 1))
        cancel_btn.bind(on_release=self.dismiss)
        add_btn = ModernButton(text="Add Selected Files", bg_color=(0.16, 0.64, 0.42, 1))
        add_btn.bind(on_release=self._confirm)
        bot.add_widget(cancel_btn)
        bot.add_widget(add_btn)
        root.add_widget(bot)

        self.content = root

    def jump_folder(self, subpath):
        base = get_default_storage()
        if subpath == "..":
            target = os.path.dirname(self.fc.path)
            if target.startswith("/storage/emulated") and len(target) < len(ANDROID_ROOT):
                target = ANDROID_ROOT
        elif subpath == "":
            target = base
        else:
            target = os.path.join(base, subpath)
        if os.path.isdir(target) and os.access(target, os.R_OK):
            self.fc.path = target

    def _on_sel(self, instance, value):
        cur = [f for f in value if os.path.isfile(f)]
        for f in list(self.selected_files):
            if f not in cur and os.path.dirname(f) == self.fc.path:
                self.selected_files.remove(f)
        for f in cur:
            if f not in self.selected_files:
                self.selected_files.append(f)
        names = ", ".join(os.path.basename(f) for f in self.selected_files)
        self.sel_lbl.text = f"Selected ({len(self.selected_files)}): {names or 'Tap files above'}"

    def _confirm(self, *args):
        if self.selected_files:
            files = list(self.selected_files)
            self.dismiss()
            self.on_files_chosen(files)


# ---------------- Export / Save Options Popup ----------------
class ExportPopup(Popup):
    def __init__(self, workspace, **kwargs):
        super().__init__(**kwargs)
        self.workspace = workspace
        self.title = f"Save / Export ({len(workspace.pages)} Pages)"
        self.title_size = "15sp"
        self.size_hint = (0.92, None)
        self.height = dp(310)
        self.background_color = (0.1, 0.12, 0.16, 1)
        self.separator_color = (0.24, 0.47, 0.96, 1)

        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))

        default_folder = os.path.dirname(workspace.pages[0].file_path) if workspace.pages else get_default_storage()
        folder_lbl = Label(
            text=f"Output Folder:\n{default_folder}",
            size_hint_y=None,
            height=dp(36),
            font_size="11.5sp",
            color=(0.72, 0.8, 0.92, 1),
            halign="left",
            valign="middle",
        )
        folder_lbl.bind(size=folder_lbl.setter("text_size"))
        root.add_widget(folder_lbl)

        self.name_input = TextInput(
            text="edited_document.pdf",
            hint_text="Output PDF Filename",
            multiline=False,
            size_hint_y=None,
            height=dp(38),
            background_color=(0.16, 0.19, 0.27, 1),
            foreground_color=(1, 1, 1, 1),
            padding=[dp(8), dp(8)],
            font_size="13sp",
        )
        root.add_widget(self.name_input)

        self.pwd_input = TextInput(
            hint_text="Optional Password (leave blank for no password)",
            multiline=False,
            size_hint_y=None,
            height=dp(38),
            background_color=(0.16, 0.19, 0.27, 1),
            foreground_color=(1, 1, 1, 1),
            padding=[dp(8), dp(8)],
            font_size="13sp",
        )
        root.add_widget(self.pwd_input)

        btn_save_merged = ModernButton(
            text="Save as Single Combined PDF",
            size_hint_y=None,
            height=dp(42),
            bg_color=(0.16, 0.64, 0.42, 1),
            font_size="13sp",
        )
        btn_save_merged.bind(on_release=lambda *a: self._run_export(split_each=False))
        root.add_widget(btn_save_merged)

        btn_split_all = ModernButton(
            text="Split & Save Every Page as Separate PDF",
            size_hint_y=None,
            height=dp(40),
            bg_color=(0.2, 0.48, 0.84, 1),
            font_size="12.5sp",
        )
        btn_split_all.bind(on_release=lambda *a: self._run_export(split_each=True))
        root.add_widget(btn_split_all)

        cancel_btn = ModernButton(
            text="Cancel",
            size_hint_y=None,
            height=dp(36),
            bg_color=(0.28, 0.3, 0.38, 1),
        )
        cancel_btn.bind(on_release=self.dismiss)
        root.add_widget(cancel_btn)

        self.content = root

    def _run_export(self, split_each=False):
        out_name = self.name_input.text.strip()
        pwd = self.pwd_input.text.strip()
        self.dismiss()
        self.workspace.export_workspace(out_name, pwd, split_each)


# ---------------- Main Interactive Workspace ----------------
class InteractivePDFWorkspace(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pages = []
        self.cards = []
        self.deleted_stack = []
        self.selected_index = 0
        self.dragging_card = None
        self.auto_scroll_ev = None

        main_box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6), size_hint=(1, 1))

        # 1. Top Header & Quick Add Toolbar
        header = RoundedCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(86),
            padding=dp(8),
            spacing=dp(6),
            bg_color=(0.13, 0.2, 0.36, 1),
        )
        top_row = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(6))
        title_lbl = Label(
            text="Live PDF & Image Workspace",
            font_size="15.5sp",
            bold=True,
            color=(1, 1, 1, 1),
            halign="left",
            valign="middle",
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))

        self.insert_target_lbl = Label(
            text="Insert Target: End",
            font_size="11.5sp",
            color=(0.62, 0.92, 0.75, 1),
            halign="right",
            valign="middle",
        )
        self.insert_target_lbl.bind(size=self.insert_target_lbl.setter("text_size"))
        top_row.add_widget(title_lbl)
        top_row.add_widget(self.insert_target_lbl)
        header.add_widget(top_row)

        add_bar = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))

        btn_open_pdf = ModernButton(text="+ PDF", bg_color=(0.22, 0.46, 0.92, 1))
        btn_open_pdf.bind(on_release=lambda *a: self.open_add_files("pdf", self.get_insert_pos()))

        btn_add_img = ModernButton(text="+ Image", bg_color=(0.18, 0.62, 0.42, 1))
        btn_add_img.bind(on_release=lambda *a: self.open_add_files("image", self.get_insert_pos()))

        btn_add_xlsx = ModernButton(text="+ XLSX", bg_color=(0.16, 0.52, 0.68, 1))
        btn_add_xlsx.bind(on_release=lambda *a: self.open_add_files("xlsx", self.get_insert_pos()))

        self.btn_undo = ModernButton(text="Undo (0)", bg_color=(0.52, 0.36, 0.22, 1))
        self.btn_undo.bind(on_release=self.undo_last_delete)

        btn_clear = ModernButton(text="Clear All", bg_color=(0.62, 0.24, 0.28, 1))
        btn_clear.bind(on_release=self.clear_workspace)

        add_bar.add_widget(btn_open_pdf)
        add_bar.add_widget(btn_add_img)
        add_bar.add_widget(btn_add_xlsx)
        add_bar.add_widget(self.btn_undo)
        add_bar.add_widget(btn_clear)
        header.add_widget(add_bar)
        main_box.add_widget(header)

        # 2. Interactive Page Preview Grid inside ScrollView
        self.scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
        self.grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, padding=[dp(2), dp(4)])
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.scroll.add_widget(self.grid)
        main_box.add_widget(self.scroll)

        # 3. Bottom Status & Save Bar
        bot_bar = RoundedCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            padding=dp(8),
            spacing=dp(8),
            bg_color=(0.11, 0.14, 0.2, 1),
        )
        self.status_lbl = Label(
            text="Tap '+ PDF' or '+ Image' above to load pages into the live editor.",
            font_size="11.5sp",
            color=(0.78, 0.85, 0.95, 1),
            halign="left",
            valign="middle",
        )
        self.status_lbl.bind(size=self.status_lbl.setter("text_size"))

        rot_all_btn = ModernButton(
            text="Rot All",
            size_hint_x=None,
            width=dp(68),
            bg_color=(0.45, 0.32, 0.76, 1),
        )
        rot_all_btn.bind(on_release=self.rotate_all_pages)

        save_btn = ModernButton(
            text="Save / Export",
            size_hint_x=None,
            width=dp(112),
            bg_color=(0.16, 0.66, 0.42, 1),
            font_size="13sp",
        )
        save_btn.bind(on_release=self.open_export_dialog)

        bot_bar.add_widget(self.status_lbl)
        bot_bar.add_widget(rot_all_btn)
        bot_bar.add_widget(save_btn)
        main_box.add_widget(bot_bar)

        self.add_widget(main_box)

        # Floating Drag Indicator Banner
        self.drag_banner = RoundedCard(
            size_hint=(None, None),
            size=(dp(150), dp(36)),
            bg_color=(0.95, 0.68, 0.15, 0.92),
            radius=8,
            padding=dp(4),
        )
        self.drag_banner_lbl = Label(text="Moving Page...", bold=True, color=(0.1, 0.1, 0.1, 1), font_size="12sp")
        self.drag_banner.add_widget(self.drag_banner_lbl)

        self._render_empty_state()

    def _render_empty_state(self):
        self.grid.clear_widgets()
        if not self.pages:
            empty_card = RoundedCard(
                orientation="vertical",
                size_hint_y=None,
                height=dp(185),
                padding=dp(16),
                bg_color=(0.12, 0.14, 0.2, 1),
            )
            msg = Label(
                text=(
                    "Workspace is Empty\n\n"
                    "1. Tap '+ PDF' to load one or more PDF files.\n"
                    "2. Hold & drag ':: Hold & Drag ::' on any card to reorder pages.\n"
                    "3. Tap '+Here' on any card to insert an Image or PDF right after it.\n"
                    "4. Tap 'Rot' or 'X' on individual cards, then tap 'Save / Export'."
                ),
                font_size="12.5sp",
                color=(0.72, 0.8, 0.92, 1),
                halign="center",
                valign="middle",
            )
            msg.bind(size=msg.setter("text_size"))
            empty_card.add_widget(msg)
            self.grid.cols = 1
            self.grid.add_widget(empty_card)

    def get_insert_pos(self):
        if not self.pages:
            return 0
        return min(len(self.pages), self.selected_index + 1)

    def select_card(self, index):
        if not self.pages:
            self.selected_index = 0
            self.insert_target_lbl.text = "Insert Target: End"
            return
        self.selected_index = max(0, min(index, len(self.pages) - 1))
        for i, card in enumerate(self.cards):
            card.set_selected(i == self.selected_index)
        self.insert_target_lbl.text = f"Insert After: Page #{self.selected_index + 1}"

    def rebuild_grid(self):
        self.grid.clear_widgets()
        self.cards.clear()
        if not self.pages:
            self._render_empty_state()
            self.select_card(0)
            return

        self.grid.cols = 2
        for i, item in enumerate(self.pages):
            card = PageCard(workspace=self, page_item=item, index=i)
            self.cards.append(card)
            self.grid.add_widget(card)
        self.select_card(min(self.selected_index, len(self.pages) - 1))

    def refresh_card_indices(self):
        for i, card in enumerate(self.cards):
            card.refresh_visuals(i)
            card.set_selected(i == self.selected_index, dragging=(card is self.dragging_card))
        self.insert_target_lbl.text = (
            f"Insert After: Page #{self.selected_index + 1}" if self.pages else "Insert Target: End"
        )

    # ---------------- Drag-and-Drop Reordering Engine ----------------
    def start_card_drag(self, card, touch):
        self.dragging_card = card
        self.scroll.do_scroll_y = False
        card.set_selected(True, dragging=True)
        self.drag_banner_lbl.text = f"Dragging Page #{card.index + 1}"
        self.drag_banner.pos = (touch.x - dp(75), touch.y + dp(15))
        if self.drag_banner.parent is None:
            self.add_widget(self.drag_banner)
        touch.grab(self)
        self.auto_scroll_ev = Clock.schedule_interval(lambda dt: self._check_edge_scroll(touch), 0.05)

    def _check_edge_scroll(self, touch):
        if not self.dragging_card or self.grid.height <= self.scroll.height:
            return
        sy_top = self.scroll.top
        sy_bot = self.scroll.y
        margin = dp(55)
        if touch.y > sy_top - margin:
            self.scroll.scroll_y = min(1.0, self.scroll.scroll_y + 0.03)
        elif touch.y < sy_bot + margin:
            self.scroll.scroll_y = max(0.0, self.scroll.scroll_y - 0.03)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self.dragging_card is not None:
            self.drag_banner.pos = (touch.x - dp(75), touch.y + dp(15))
            gx, gy = self.grid.to_widget(*touch.pos)
            for target_card in list(self.cards):
                if target_card is not self.dragging_card and target_card.collide_point(gx, gy):
                    old_idx = self.cards.index(self.dragging_card)
                    new_idx = self.cards.index(target_card)
                    if old_idx != new_idx:
                        self._swap_cards_live(old_idx, new_idx)
                    break
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self and self.dragging_card is not None:
            touch.ungrab(self)
            if self.auto_scroll_ev:
                self.auto_scroll_ev.cancel()
                self.auto_scroll_ev = None
            if self.drag_banner.parent is not None:
                self.remove_widget(self.drag_banner)
            final_idx = self.dragging_index()
            self.dragging_card = None
            self.scroll.do_scroll_y = True
            self.select_card(final_idx)
            self.refresh_card_indices()
            self.set_status(True, f"Moved page to position #{final_idx + 1}.")
            return True
        return super().on_touch_up(touch)

    def dragging_index(self):
        if self.dragging_card and self.dragging_card in self.cards:
            return self.cards.index(self.dragging_card)
        return self.selected_index

    def _swap_cards_live(self, from_idx, to_idx):
        item = self.pages.pop(from_idx)
        self.pages.insert(to_idx, item)

        card = self.cards.pop(from_idx)
        self.cards.insert(to_idx, card)

        self.grid.clear_widgets()
        for c in self.cards:
            self.grid.add_widget(c)

        self.selected_index = to_idx
        self.drag_banner_lbl.text = f"Drop at Position #{to_idx + 1}"
        self.refresh_card_indices()

    # ---------------- Page Manipulation Actions ----------------
    def move_page(self, from_idx, to_idx):
        if 0 <= from_idx < len(self.pages) and 0 <= to_idx < len(self.pages):
            self._swap_cards_live(from_idx, to_idx)
            self.set_status(True, f"Moved page #{from_idx + 1} to #{to_idx + 1}.")

    def rotate_page_at(self, index):
        if 0 <= index < len(self.pages):
            item = self.pages[index]
            item.rotation = (item.rotation + 90) % 360
            self.cards[index].refresh_visuals(index)
            self.set_status(True, f"Rotated page #{index + 1} to {item.rotation} deg.")

    def rotate_all_pages(self, *args):
        if not self.pages:
            return
        for i, item in enumerate(self.pages):
            item.rotation = (item.rotation + 90) % 360
            self.cards[i].refresh_visuals(i)
        self.set_status(True, "Rotated all pages by 90 deg.")

    def delete_page_at(self, index):
        if 0 <= index < len(self.pages):
            removed = self.pages.pop(index)
            self.deleted_stack.append((index, removed))
            self.btn_undo.text = f"Undo ({len(self.deleted_stack)})"
            self.rebuild_grid()
            self.set_status(True, f"Removed page #{index + 1}. Tap 'Undo' to restore.")

    def undo_last_delete(self, *args):
        if not self.deleted_stack:
            self.set_status(False, "Nothing to undo.")
            return
        idx, item = self.deleted_stack.pop()
        ins_idx = min(idx, len(self.pages))
        self.pages.insert(ins_idx, item)
        self.btn_undo.text = f"Undo ({len(self.deleted_stack)})"
        self.selected_index = ins_idx
        self.rebuild_grid()
        self.set_status(True, f"Restored page at #{ins_idx + 1}.")

    def clear_workspace(self, *args):
        self.pages.clear()
        self.deleted_stack.clear()
        self.btn_undo.text = "Undo (0)"
        self.rebuild_grid()
        self.set_status(True, "Workspace cleared.")

    def open_zoom_preview(self, index):
        if 0 <= index < len(self.pages):
            PageZoomPopup(workspace=self, index=index).open()

    # ---------------- Insert Images / PDFs / XLSX at Any Spot ----------------
    def prompt_insert_at(self, target_index):
        pop = Popup(
            title=f"Insert at Page Position #{target_index + 1}",
            size_hint=(0.86, None),
            height=dp(220),
            background_color=(0.1, 0.12, 0.16, 1),
            separator_color=(0.24, 0.47, 0.96, 1),
        )
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))

        b_img = ModernButton(text="Insert Image(s) as PDF Page here", bg_color=(0.18, 0.62, 0.42, 1))
        b_img.bind(on_release=lambda *a: (pop.dismiss(), self.open_add_files("image", target_index)))

        b_pdf = ModernButton(text="Insert Another PDF's Pages here", bg_color=(0.22, 0.46, 0.92, 1))
        b_pdf.bind(on_release=lambda *a: (pop.dismiss(), self.open_add_files("pdf", target_index)))

        b_cancel = ModernButton(text="Cancel", bg_color=(0.28, 0.3, 0.38, 1))
        b_cancel.bind(on_release=pop.dismiss)

        box.add_widget(b_img)
        box.add_widget(b_pdf)
        box.add_widget(b_cancel)
        pop.content = box
        pop.open()

    def open_add_files(self, mode, insert_at):
        if mode == "pdf":
            filters = ["*.pdf", "*.PDF"]
            title = f"Select PDF(s) to Insert at Position #{insert_at + 1}"
        elif mode == "image":
            filters = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp", "*.JPG", "*.PNG"]
            title = f"Select Image(s) to Insert at Position #{insert_at + 1}"
        else:
            filters = ["*.xlsx", "*.XLSX"]
            title = f"Select Excel (.xlsx) to Insert at Position #{insert_at + 1}"

        FilePickerPopup(
            title=title,
            filters=filters,
            on_files_chosen=lambda files: self._schedule_load_files(files, mode, insert_at),
        ).open()

    def _schedule_load_files(self, files, mode, insert_at):
        self.set_status(True, "Loading pages into workspace...")
        Clock.schedule_once(lambda dt: self._load_files_main_thread(files, mode, insert_at), 0.05)

    def _convert_xlsx_to_temp_pdf(self, xlsx_path):
        wb = load_workbook(xlsx_path, data_only=True)
        temp_pdf = os.path.join(
            os.path.dirname(xlsx_path),
            f".tmp_ws_{os.path.splitext(os.path.basename(xlsx_path))[0]}.pdf",
        )
        page_w, page_h = landscape(letter)
        margin = 36
        c = canvas.Canvas(temp_pdf, pagesize=(page_w, page_h))
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            while rows and all(cell is None or str(cell).strip() == "" for cell in rows[-1]):
                rows.pop()
            c.setFont("Helvetica-Bold", 12)
            c.drawString(margin, page_h - margin, f"Sheet: {sheet_name}")
            y = page_h - margin - 24
            if not rows:
                c.showPage()
                continue
            max_cols = max(len(r) for r in rows) if rows else 1
            col_w = max(45, (page_w - 2 * margin) / max(1, min(max_cols, 12)))
            max_chars = max(6, int(col_w / 5.2))
            row_h = 18
            for r_idx, row in enumerate(rows):
                if y < margin + row_h:
                    c.showPage()
                    y = page_h - margin - 10
                c.setFont("Helvetica-Bold" if r_idx == 0 else "Helvetica", 8.5)
                for c_idx, cell in enumerate(row[:12]):
                    x = margin + c_idx * col_w
                    text = "" if cell is None else str(cell).replace("\n", " ").strip()
                    if len(text) > max_chars:
                        text = text[: max_chars - 1] + "..."
                    c.rect(x, y - 4, col_w, row_h, stroke=1, fill=0)
                    c.drawString(x + 4, y + 2, text)
                y -= row_h
            c.showPage()
        c.save()
        return temp_pdf

    def _extract_page_text_safe(self, page):
        try:
            if hasattr(page, "extract_text"):
                return (page.extract_text() or "").strip()
            if hasattr(page, "extractText"):
                return (page.extractText() or "").strip()
        except Exception:
            pass
        return ""

    def _load_files_main_thread(self, files, mode, insert_at):
        new_items = []
        try:
            for f in files:
                if mode == "image":
                    new_items.append(PageItem(source_type="image", file_path=f, page_index=0))
                elif mode == "pdf":
                    reader = PdfReader(f)
                    pages = get_pdf_pages(reader)
                    for idx, pg in enumerate(pages):
                        txt = self._extract_page_text_safe(pg)
                        new_items.append(
                            PageItem(
                                source_type="pdf",
                                file_path=f,
                                page_index=idx,
                                pre_extracted_text=txt,
                            )
                        )
                elif mode == "xlsx":
                    temp_pdf = self._convert_xlsx_to_temp_pdf(f)
                    reader = PdfReader(temp_pdf)
                    pages = get_pdf_pages(reader)
                    for idx, pg in enumerate(pages):
                        txt = self._extract_page_text_safe(pg)
                        new_items.append(
                            PageItem(
                                source_type="pdf",
                                file_path=temp_pdf,
                                page_index=idx,
                                pre_extracted_text=txt,
                            )
                        )

            pos = max(0, min(insert_at, len(self.pages)))
            for offset, item in enumerate(new_items):
                self.pages.insert(pos + offset, item)
            if new_items:
                self.selected_index = pos + len(new_items) - 1
            self.rebuild_grid()
            self.set_status(
                True,
                f"Inserted {len(new_items)} page(s) at position #{pos + 1}. Total: {len(self.pages)} pages.",
            )
        except Exception as e:
            self.set_status(False, f"Load error: {str(e)}")

    # ---------------- Export & Save Final PDF ----------------
    def open_export_dialog(self, *args):
        if not self.pages:
            self.set_status(False, "Add at least one PDF or Image before saving!")
            return
        ExportPopup(workspace=self).open()

    def export_workspace(self, out_name, password, split_each=False):
        self.set_status(True, "Saving PDF...")
        Clock.schedule_once(lambda dt: self._export_main_thread(out_name, password, split_each), 0.05)

    def _item_to_pdf_page(self, item, reader_cache):
        if item.source_type == "pdf":
            if item.file_path not in reader_cache:
                reader_cache[item.file_path] = PdfReader(item.file_path)
            reader = reader_cache[item.file_path]
            page = get_pdf_pages(reader)[item.page_index]
            return rotate_pdf_page_obj(page, item.rotation)
        else:
            with PILImage.open(item.file_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                if item.rotation % 360 != 0:
                    im = im.rotate(-item.rotation, expand=True)
                pdf_bytes = io.BytesIO()
                im.save(pdf_bytes, format="PDF", resolution=150.0)
                pdf_bytes.seek(0)
                img_reader = PdfReader(pdf_bytes)
                return get_pdf_pages(img_reader)[0]

    def _export_main_thread(self, out_name, password, split_each):
        try:
            items = list(self.pages)
            folder = os.path.dirname(items[0].file_path) if items else get_default_storage()
            reader_cache = {}

            if split_each:
                base_prefix = os.path.splitext(out_name)[0] if out_name else "page"
                for idx, item in enumerate(items):
                    writer = PdfWriter()
                    page_obj = self._item_to_pdf_page(item, reader_cache)
                    add_pdf_page(writer, page_obj)
                    if password and hasattr(writer, "encrypt"):
                        writer.encrypt(password)
                    p_out = get_safe_output_path(folder, "", f"{base_prefix}_{idx + 1}.pdf")
                    with open(p_out, "wb") as f:
                        writer.write(f)
                msg = f"Saved {len(items)} separate PDF pages in:\n{folder}"
            else:
                writer = PdfWriter()
                for item in items:
                    page_obj = self._item_to_pdf_page(item, reader_cache)
                    add_pdf_page(writer, page_obj)
                if password and hasattr(writer, "encrypt"):
                    writer.encrypt(password)
                final_path = get_safe_output_path(folder, out_name, "edited_document.pdf")
                with open(final_path, "wb") as f:
                    writer.write(f)
                msg = f"Saved ({len(items)} pages) to:\n{final_path}"
            self.set_status(True, msg)
        except Exception as e:
            self.set_status(False, f"Export Error: {str(e)}")

    def set_status(self, ok, text):
        self.status_lbl.text = text
        self.status_lbl.color = (0.5, 0.96, 0.68, 1) if ok else (1, 0.52, 0.52, 1)


class PDFUtilityApp(App):
    def build(self):
        request_android_permissions()
        self.title = "Interactive PDF Workspace"
        return InteractivePDFWorkspace()


if __name__ == "__main__":
    PDFUtilityApp().run()
