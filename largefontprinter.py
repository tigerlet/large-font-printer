import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.affinity import scale
from shapely.ops import unary_union
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A3, A2, A1, A0, LETTER, LEGAL
from shapely.errors import TopologicalError
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk
import io

# ==================== Data Structure Definitions ====================
"""
ContourPoint: 2D coordinate point, tuple[float, float]
RawContour: Raw contour data, list[ContourPoint]
ProcessedPolygon: Processed polygon structure {
    "polygon": shapely.Polygon,
    "is_outer": bool,   # Whether it's an outer contour
    "children": list    # Nested child contours
}
"""

# ==================== Custom Exception ====================
class FontProcessingError(Exception):
    """Custom exception for font processing errors"""
    def __init__(self, message):
        super().__init__(f"Font processing error: {message}")

# ==================== Fill Style Definitions ====================
FILL_STYLES = {
    'solid': 'Solid Fill',
    'horizontal': 'Horizontal Gradient',
    'vertical': 'Vertical Gradient',
    'radial': 'Radial Gradient',
    'crosshatch': 'Crosshatch Pattern',
    'dots': 'Dot Pattern',
    'lines': 'Line Pattern',
    'grid': 'Grid Pattern'
}

PAGE_SIZES = {
    'A4': A4,
    'A3': A3,
    'A2': A2,
    'A1': A1,
    'A0': A0,
    'Letter': LETTER,
    'Legal': LEGAL
}

# ==================== Contour Collection Pen ====================
class ContourPen(BasePen):
    """Font contour collection tool (inherits from BasePen)"""
    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.contours = []
        self.current_contour = []

    def _moveTo(self, pt):
        """Start a new contour path"""
        self.current_contour = [pt]

    def _lineTo(self, pt):
        """Draw a straight line to the specified point"""
        self.current_contour.append(pt)

    def cubic_bezier(self, t, P0, P1, P2, P3):
        """Calculate point on cubic Bezier curve"""
        x = (1 - t) ** 3 * P0[0] + 3 * (1 - t) ** 2 * t * P1[0] + 3 * (1 - t) * t ** 2 * P2[0] + t ** 3 * P3[0]
        y = (1 - t) ** 3 * P0[1] + 3 * (1 - t) ** 2 * t * P1[1] + 3 * (1 - t) * t ** 2 * P2[1] + t ** 3 * P3[1]
        return (x, y)

    def _curveToOne(self, pt1, pt2, pt3):
        """Process cubic Bezier curve"""
        p0 = self.current_contour[-1]
        t_values = np.linspace(0, 1, 100)
        curve_points = [self.cubic_bezier(t, p0, pt1, pt2, pt3) for t in t_values]
        self.current_contour.extend(curve_points)

    def _closePath(self):
        """Close the current contour path"""
        if len(self.current_contour) > 0:
            self.contours.append(self.current_contour)
            self.current_contour = []

# ==================== Glyph Processor ====================
class GlyphProcessor:
    def __init__(self, font_path, char, scale_factor, page_size):
        self.ttfont = TTFont(font_path)
        self.cmp = self.ttfont.getBestCmap()
        self.glyph_name = self.cmp[ord(char)]
        self.glyph_set = self.ttfont.getGlyphSet()
        self.glyph = self.glyph_set[self.glyph_name]
        self.scale = scale_factor
        self.page_w, self.page_h = page_size

    def process(self):
        pen = ContourPen(self.glyph_set)
        transform = Transform().scale(self.scale, self.scale).translate(0, 0)
        transformed_pen = TransformPen(pen, transform)
        self.glyph.draw(transformed_pen)
        hierarchy = self.build_contour_hierarchy(pen.contours)
        base_poly = self.build_geometry(hierarchy)
        return self._paginate(base_poly)

    def _apply_transform(self, points, matrix):
        """Apply affine transformation"""
        return [tuple(np.dot(matrix, (x, y, 1))[:2]) for x, y in points]

    def build_contour_hierarchy(self, contours):
        """Build hierarchical structure with holes"""
        processed = []
        
        for contour in contours:
            coords = [(x, y) for x, y in contour]
            if len(coords) < 3:
                continue
            
            area = 0.5 * sum(x * y1 - x1 * y
                             for (x, y), (x1, y1) in zip(coords, coords[1:] + coords[:1]))
            is_outer = area < 0
            
            poly = Polygon(coords).buffer(0)
            processed.append({
                "polygon": poly,
                "is_outer": is_outer,
                "children": []
            })
        
        processed.sort(key=lambda x: x["polygon"].area, reverse=True)
        hierarchy = []
        
        for poly in processed:
            if poly["is_outer"]:
                hierarchy.insert(0, poly)
        
        for poly in processed:
            if not poly["is_outer"]:
                for parent in hierarchy:
                    if parent["polygon"].contains(poly["polygon"]):
                        parent["children"].append(poly)
                        break
        
        return hierarchy

    def build_geometry(self, hierarchy):
        """Build geometric shape"""
        valid_polys = []
        
        for outer in hierarchy:
            if outer["children"]:
                holes = [child["polygon"].exterior.coords for child in outer["children"]]
                shape = Polygon(outer["polygon"].exterior, holes=holes).buffer(0)
            else:
                shape = outer["polygon"]
            valid_polys.append(shape)
        
        try:
            return unary_union(valid_polys).buffer(0)
        except TopologicalError:
            return unary_union([p.buffer(0) for p in valid_polys])

    def _paginate(self, geometry):
        """Dynamic pagination processing"""
        minx, miny, maxx, maxy = geometry.bounds
        cols = int(np.ceil((maxx - minx) / self.page_w))
        rows = int(np.ceil((maxy - miny) / self.page_h))
        
        pages = []
        for c in range(cols):
            for r in range(rows):
                x0 = minx + c * self.page_w
                y0 = miny + r * self.page_h
                page_box = box(x0, y0, x0 + self.page_w, y0 + self.page_h)
                
                try:
                    page_content = geometry.intersection(page_box)
                except TopologicalError:
                    page_content = geometry.buffer(0).intersection(page_box)
                
                if not page_content.is_empty:
                    transformed = self._transform_coords(page_content, x0, y0)
                    pages.append(transformed)
        
        # Return a custom object containing all information
        class PageList(list):
            def __init__(self, pages, total_bounds, page_info):
                super().__init__(pages)
                self.total_bounds = total_bounds
                self.page_info = page_info
        
        # Build page info list
        page_info_list = []
        idx = 0
        for c in range(cols):
            for r in range(rows):
                x0 = minx + c * self.page_w
                y0 = miny + r * self.page_h
                page_box = box(x0, y0, x0 + self.page_w, y0 + self.page_h)
                
                try:
                    page_content = geometry.intersection(page_box)
                except TopologicalError:
                    page_content = geometry.buffer(0).intersection(page_box)
                
                if not page_content.is_empty:
                    page_info_list.append({
                        'page': pages[idx],
                        'original_bounds': (x0, y0, x0 + self.page_w, y0 + self.page_h),
                        'col': c,
                        'row': r,
                        'idx': idx
                    })
                    idx += 1
        
        return PageList(pages, (minx, miny, maxx, maxy), page_info_list)

    def _transform_coords(self, geometry, dx, dy):
        """Transform coordinates to page local coordinate system"""
        if geometry.geom_type == 'Polygon':
            return Polygon(
                [(x - dx, self.page_h - (y - dy)) for x, y in geometry.exterior.coords],
                [[(x - dx, self.page_h - (y - dy)) for x, y in ring.coords]
                 for ring in geometry.interiors]
            )
        elif geometry.geom_type == 'MultiPolygon':
            return MultiPolygon([self._transform_coords(p, dx, dy)
                                 for p in geometry.geoms])
        return geometry

# ==================== PDF Generator (Supports Multiple Fill Styles) ====================
class PDFGenerator:
    def __init__(self, filename, page_size):
        self.canvas = canvas.Canvas(filename, pagesize=page_size)
        self.page_w, self.page_h = page_size

    def render(self, pages, fill_style='solid', color=(1, 0, 0), 
               second_color=(0, 0, 1), pattern_density=10):
        """
        Render PDF pages
        :param pages: List of page geometry data
        :param fill_style: Fill style
        :param color: Primary color (RGB 0-1)
        :param second_color: Secondary color (for gradients)
        :param pattern_density: Pattern density
        """
        for idx, page in enumerate(pages):
            if idx > 0:
                self.canvas.showPage()
            self._draw_page(page, fill_style, color, second_color, pattern_density)
        self.canvas.save()

    def _draw_page(self, geometry, fill_style, color, second_color, pattern_density):
        """Draw a single page"""
        path = self.canvas.beginPath()
        
        if geometry.geom_type == 'Polygon':
            self._render_polygon(path, geometry)
        elif geometry.geom_type == 'MultiPolygon':
            for poly in geometry.geoms:
                self._render_polygon(path, poly)
        
        self.canvas.translate(0, self.page_h)
        self.canvas.scale(1, -1)
        
        self._apply_fill(fill_style, color, second_color, pattern_density)
        self.canvas.drawPath(path, fill=1, stroke=0)

    def _render_polygon(self, path, polygon):
        """Render a single polygon"""
        self._add_contour(path, polygon.exterior)
        for hole in polygon.interiors:
            self._add_contour(path, hole)

    def _add_contour(self, path, ring):
        """Add contour path"""
        coords = list(ring.coords)
        path.moveTo(*coords[0])
        for pt in coords[1:]:
            path.lineTo(*pt)
        path.close()

    def _apply_fill(self, fill_style, color, second_color, pattern_density):
        """Apply fill style"""
        if fill_style == 'solid':
            self.canvas.setFillColorRGB(*color)
        
        elif fill_style == 'horizontal':
            from reportlab.lib.colors import LinearGradient
            gradient = LinearGradient((0, 0), (self.page_w, 0))
            gradient.addStop(0.0, color)
            gradient.addStop(1.0, second_color)
            self.canvas.setFillColor(gradient)
        
        elif fill_style == 'vertical':
            from reportlab.lib.colors import LinearGradient
            gradient = LinearGradient((0, 0), (0, self.page_h))
            gradient.addStop(0.0, color)
            gradient.addStop(1.0, second_color)
            self.canvas.setFillColor(gradient)
        
        elif fill_style == 'radial':
            from reportlab.lib.colors import RadialGradient
            gradient = RadialGradient((self.page_w/2, self.page_h/2), 0, 
                                     (self.page_w/2, self.page_h/2), max(self.page_w, self.page_h)/2)
            gradient.addStop(0.0, color)
            gradient.addStop(1.0, second_color)
            self.canvas.setFillColor(gradient)
        
        elif fill_style == 'crosshatch':
            self._apply_pattern_fill('crosshatch', color, pattern_density)
        
        elif fill_style == 'dots':
            self._apply_pattern_fill('dots', color, pattern_density)
        
        elif fill_style == 'lines':
            self._apply_pattern_fill('lines', color, pattern_density)
        
        elif fill_style == 'grid':
            self._apply_pattern_fill('grid', color, pattern_density)

    def _apply_pattern_fill(self, pattern_type, color, density):
        """Apply pattern fill"""
        from reportlab.pdfgen import patterns
        pat = patterns.Pattern(612, 792)
        
        if pattern_type == 'crosshatch':
            pat.setFillColorRGB(*color)
            for i in range(-1000, 1000, density):
                pat.line(i, 0, i + 1000, 1000)
                pat.line(i, 1000, i + 1000, 0)
        
        elif pattern_type == 'dots':
            pat.setFillColorRGB(*color)
            for x in range(0, 612, density):
                for y in range(0, 792, density):
                    pat.circle(x, y, 2, fill=1)
        
        elif pattern_type == 'lines':
            pat.setFillColorRGB(*color)
            for y in range(0, 792, density):
                pat.line(0, y, 612, y)
        
        elif pattern_type == 'grid':
            pat.setFillColorRGB(*color)
            for x in range(0, 612, density):
                pat.line(x, 0, x, 792)
            for y in range(0, 792, density):
                pat.line(0, y, 612, y)
        
        self.canvas.setFillPattern(pat)

# ==================== Graphical User Interface ====================
class BigFontPrintApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Large Character Pagination Printing System")
        self.root.geometry("900x700")
        
        # Default configuration
        self.config = {
            'font_path': '',
            'char': 'A',
            'scale_factor': 5,
            'page_size': 'A4',
            'output_file': 'output.pdf',
            'fill_style': 'solid',
            'primary_color': (1.0, 0.0, 0.0),  # Red
            'secondary_color': (0.0, 0.0, 1.0),  # Blue
            'pattern_density': 10
        }
        
        # Create GUI
        self.create_widgets()
        
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left control panel
        left_panel = ttk.Frame(main_frame, width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # Right preview area
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # ========== Left Control Panel ==========
        
        # Font selection
        ttk.Label(left_panel, text="Font File:").pack(anchor=tk.W, pady=(10, 2))
        font_frame = ttk.Frame(left_panel)
        font_frame.pack(fill=tk.X)
        self.font_path_entry = ttk.Entry(font_frame)
        self.font_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(font_frame, text="Browse", command=self.browse_font).pack(side=tk.RIGHT)
        
        # Character input
        ttk.Label(left_panel, text="Input Character:").pack(anchor=tk.W, pady=(10, 2))
        self.char_entry = ttk.Entry(left_panel, font=('Arial', 20))
        self.char_entry.insert(0, 'A')
        self.char_entry.pack(fill=tk.X)
        
        # Scale factor
        ttk.Label(left_panel, text="Scale Factor:").pack(anchor=tk.W, pady=(10, 2))
        self.scale_label = ttk.Label(left_panel, text="5.0x")
        self.scale_slider = ttk.Scale(left_panel, from_=1, to=20, orient=tk.HORIZONTAL, 
                                      command=self.update_scale_label)
        self.scale_slider.set(5)
        self.scale_slider.pack(fill=tk.X)
        self.scale_label.pack(anchor=tk.W)
        
        # Page size
        ttk.Label(left_panel, text="Page Size:").pack(anchor=tk.W, pady=(10, 2))
        self.page_size_combobox = ttk.Combobox(left_panel, values=list(PAGE_SIZES.keys()))
        self.page_size_combobox.set('A4')
        self.page_size_combobox.pack(fill=tk.X)
        
        # Fill style
        ttk.Label(left_panel, text="Fill Style:").pack(anchor=tk.W, pady=(10, 2))
        self.fill_style_combobox = ttk.Combobox(left_panel, values=list(FILL_STYLES.values()))
        self.fill_style_combobox.set('Solid Fill')
        self.fill_style_combobox.bind('<<ComboboxSelected>>', self.update_fill_options)
        self.fill_style_combobox.pack(fill=tk.X)
        
        # Primary color
        ttk.Label(left_panel, text="Primary Color:").pack(anchor=tk.W, pady=(10, 2))
        color_frame = ttk.Frame(left_panel)
        color_frame.pack(fill=tk.X)
        self.color_button = ttk.Button(color_frame, text="Choose Color", command=self.choose_primary_color)
        self.color_button.pack(side=tk.LEFT)
        self.color_preview = ttk.Label(color_frame, width=10, background='#FF0000')
        self.color_preview.pack(side=tk.RIGHT)
        
        # Secondary color (for gradients)
        self.secondary_color_frame = ttk.Frame(left_panel)
        ttk.Label(self.secondary_color_frame, text="Secondary Color:").pack(anchor=tk.W)
        color2_frame = ttk.Frame(self.secondary_color_frame)
        color2_frame.pack(fill=tk.X)
        self.color2_button = ttk.Button(color2_frame, text="Choose Color", command=self.choose_secondary_color)
        self.color2_button.pack(side=tk.LEFT)
        self.color2_preview = ttk.Label(color2_frame, width=10, background='#0000FF')
        self.color2_preview.pack(side=tk.RIGHT)
        self.secondary_color_frame.pack(fill=tk.X)
        
        # Pattern density
        self.pattern_density_frame = ttk.Frame(left_panel)
        ttk.Label(self.pattern_density_frame, text="Pattern Density:").pack(anchor=tk.W, pady=(10, 2))
        self.density_label = ttk.Label(self.pattern_density_frame, text="10")
        self.density_slider = ttk.Scale(self.pattern_density_frame, from_=5, to=50, orient=tk.HORIZONTAL,
                                        command=self.update_density_label)
        self.density_slider.set(10)
        self.density_slider.pack(fill=tk.X)
        self.density_label.pack(anchor=tk.W)
        self.pattern_density_frame.pack(fill=tk.X)
        
        # Output file
        ttk.Label(left_panel, text="Output File:").pack(anchor=tk.W, pady=(10, 2))
        output_frame = ttk.Frame(left_panel)
        output_frame.pack(fill=tk.X)
        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.insert(0, 'output.pdf')
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(output_frame, text="Browse", command=self.browse_output).pack(side=tk.RIGHT)
        
        # Generate button
        ttk.Button(left_panel, text="Generate PDF", command=self.generate_pdf, style='Accent.TButton').pack(
            fill=tk.X, pady=20)
        
        # Status label
        self.status_label = ttk.Label(left_panel, text="Ready", foreground='green')
        self.status_label.pack(anchor=tk.W)
        
        # ========== Right Preview Area ==========
        # Page thumbnail area (grid layout)
        ttk.Label(right_panel, text="Page Layout Preview (Click for Details)").pack(anchor=tk.W, pady=5)
        self.thumbnail_frame = ttk.Frame(right_panel)
        self.thumbnail_frame.pack(fill=tk.X)
        
        # Horizontal scrollbar
        self.thumbnail_hscrollbar = ttk.Scrollbar(self.thumbnail_frame, orient=tk.HORIZONTAL)
        self.thumbnail_hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Vertical scrollbar
        self.thumbnail_vscrollbar = ttk.Scrollbar(self.thumbnail_frame, orient=tk.VERTICAL)
        self.thumbnail_vscrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Scrollable canvas
        self.thumbnail_canvas = tk.Canvas(self.thumbnail_frame, bg='lightgray', height=180, 
                                          scrollregion=(0, 0, 1000, 1000),
                                          xscrollcommand=self.thumbnail_hscrollbar.set,
                                          yscrollcommand=self.thumbnail_vscrollbar.set)
        self.thumbnail_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure scrollbars
        self.thumbnail_hscrollbar.configure(command=self.thumbnail_canvas.xview)
        self.thumbnail_vscrollbar.configure(command=self.thumbnail_canvas.yview)
        
        # Detailed preview area
        ttk.Label(right_panel, text="Detailed Preview").pack(anchor=tk.W, pady=5)
        self.preview_canvas = tk.Canvas(right_panel, bg='white', relief=tk.SUNKEN, borderwidth=2)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Save page data
        self.pages_data = []
        self.selected_page = 0
        
        # Update fill options display
        self.update_fill_options()
    
    def browse_font(self):
        """Browse for font file"""
        path = filedialog.askopenfilename(filetypes=[('TrueType Font', '*.ttf'), ('OpenType Font', '*.otf')])
        if path:
            self.font_path_entry.delete(0, tk.END)
            self.font_path_entry.insert(0, path)
    
    def browse_output(self):
        """Browse for output file"""
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF File', '*.pdf')])
        if path:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, path)
    
    def choose_primary_color(self):
        """Choose primary color"""
        color = colorchooser.askcolor(title="Choose Primary Color")
        if color[1]:
            self.config['primary_color'] = self.hex_to_rgb(color[1])
            self.color_preview.config(background=color[1])
    
    def choose_secondary_color(self):
        """Choose secondary color"""
        color = colorchooser.askcolor(title="Choose Secondary Color")
        if color[1]:
            self.config['secondary_color'] = self.hex_to_rgb(color[1])
            self.color2_preview.config(background=color[1])
    
    def hex_to_rgb(self, hex_color):
        """Convert hex color to RGB (0-1)"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    
    def update_scale_label(self, value):
        """Update scale factor label"""
        self.scale_label.config(text=f"{float(value):.1f}x")
    
    def update_density_label(self, value):
        """Update pattern density label"""
        self.density_label.config(text=f"{int(float(value))}")
    
    def update_fill_options(self, event=None):
        """Show/hide options based on fill style"""
        style_name = self.fill_style_combobox.get()
        style_key = list(FILL_STYLES.keys())[list(FILL_STYLES.values()).index(style_name)]
        
        # Show/hide secondary color (needed for gradients)
        if style_key in ['horizontal', 'vertical', 'radial']:
            self.secondary_color_frame.pack(fill=tk.X)
        else:
            self.secondary_color_frame.pack_forget()
        
        # Show/hide pattern density (needed for patterns)
        if style_key in ['crosshatch', 'dots', 'lines', 'grid']:
            self.pattern_density_frame.pack(fill=tk.X)
        else:
            self.pattern_density_frame.pack_forget()
    
    def generate_pdf(self):
        """Generate PDF"""
        try:
            # Get configuration
            self.config['font_path'] = self.font_path_entry.get()
            self.config['char'] = self.char_entry.get()
            self.config['scale_factor'] = float(self.scale_slider.get())
            self.config['page_size'] = self.page_size_combobox.get()
            self.config['output_file'] = self.output_entry.get()
            
            style_name = self.fill_style_combobox.get()
            self.config['fill_style'] = list(FILL_STYLES.keys())[list(FILL_STYLES.values()).index(style_name)]
            self.config['pattern_density'] = int(self.density_slider.get())
            
            # Validate input
            if not self.config['font_path']:
                messagebox.showerror("Error", "Please select a font file")
                return
            
            if not self.config['char']:
                messagebox.showerror("Error", "Please enter a character")
                return
            
            if len(self.config['char']) > 1:
                messagebox.showerror("Error", "Please enter only one character")
                return
            
            # Update status
            self.status_label.config(text="Processing...", foreground='orange')
            self.root.update()
            
            # Process glyph
            page_size_tuple = PAGE_SIZES[self.config['page_size']]
            processor = GlyphProcessor(
                self.config['font_path'],
                self.config['char'],
                self.config['scale_factor'],
                page_size_tuple
            )
            pages = processor.process()
            
            if not pages:
                messagebox.showwarning("Warning", "No pages generated")
                self.status_label.config(text="Ready", foreground='green')
                return
            
            # Generate PDF
            pdf_gen = PDFGenerator(self.config['output_file'], page_size_tuple)
            pdf_gen.render(
                pages,
                fill_style=self.config['fill_style'],
                color=self.config['primary_color'],
                second_color=self.config['secondary_color'],
                pattern_density=self.config['pattern_density']
            )
            
            # Update preview
            self.update_preview(pages)
            
            # Update status
            self.status_label.config(text=f"Success! Generated {len(pages)} pages", foreground='green')
            messagebox.showinfo("Success", f"PDF generated successfully! Total pages: {len(pages)}")
            
        except Exception as e:
            self.status_label.config(text=f"Failed: {str(e)}", foreground='red')
            messagebox.showerror("Error", f"Generation failed: {str(e)}")
    
    def update_preview(self, pages):
        """Update preview (thumbnails + detailed view)"""
        if not pages:
            return
        
        # Save page data
        self.pages_data = pages
        self.selected_page = 0
        
        # Draw thumbnails first
        self.draw_thumbnails(pages)
        
        # Draw detailed preview
        self.draw_detail_preview(pages[0], 0)
    
    def draw_thumbnails(self, pages):
        """Draw page thumbnails in grid layout"""
        canvas = self.thumbnail_canvas
        canvas.delete('all')
        
        if not pages:
            return
        
        # Get page size
        page_size_tuple = PAGE_SIZES[self.config['page_size']]
        page_w, page_h = page_size_tuple
        
        # Get extra info saved during pagination
        page_info_list = getattr(pages, 'page_info', [])
        total_bounds = getattr(pages, 'total_bounds', None)
        
        if not page_info_list or total_bounds is None:
            # Fallback method
            self.draw_thumbnails_fallback(pages)
            return
        
        minx_all, miny_all, maxx_all, maxy_all = total_bounds
        
        # Calculate grid columns and rows
        cols = int((maxx_all - minx_all) / page_w) + 1
        rows = int((maxy_all - miny_all) / page_h) + 1
        
        # Ensure at least 1x1 grid
        cols = max(cols, 1)
        rows = max(rows, 1)
        
        # Thumbnail dimensions
        thumb_width = 70
        thumb_height = 60
        padding = 10
        spacing = 5
        
        # Calculate canvas size
        canvas_width = cols * (thumb_width + spacing) + padding * 2
        canvas_height = rows * (thumb_height + spacing) + padding * 2 + 20
        canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        # Calculate scale for thumbnails
        thumb_page_scale_w = thumb_width / page_w * 0.9
        thumb_page_scale_h = thumb_height / page_h * 0.9
        thumb_page_scale = min(thumb_page_scale_w, thumb_page_scale_h)
        
        # Create grid mapping
        grid = {}
        for info in page_info_list:
            col_idx = info['col']
            row_idx = info['row']
            grid[(row_idx, col_idx)] = info
        
        # Draw thumbnails in row-major order
        for row_idx in range(rows):
            for col_idx in range(cols):
                # Calculate thumbnail position
                x = padding + col_idx * (thumb_width + spacing)
                y = padding + row_idx * (thumb_height + spacing)
                
                # Check if there's a page at this grid position
                key = (row_idx, col_idx)
                if key in grid:
                    info = grid[key]
                    page = info['page']
                    page_idx = page_info_list.index(info)
                    
                    # Create thumbnail background
                    thumb_bg = canvas.create_rectangle(x, y, x + thumb_width, y + thumb_height,
                                                       fill='white', outline='gray', width=2, tags=('thumb_bg',))
                    
                    # Draw polygon on thumbnail
                    def draw_thumbnail_polygon(poly):
                        exterior_coords = list(poly.exterior.coords)
                        points = []
                        for px, py in exterior_coords:
                            nx = x + px * thumb_page_scale + thumb_width * 0.05
                            ny = y + (page_h - py) * thumb_page_scale + thumb_height * 0.05
                            points.append((nx, ny))
                        
                        if len(points) >= 3:
                            flat_points = [coord for point in points for coord in point]
                            canvas.create_polygon(flat_points, fill=self.rgb_to_hex(self.config['primary_color']), 
                                                  outline='black', width=1)
                        
                        # Draw holes
                        for hole in poly.interiors:
                            hole_coords = list(hole.coords)
                            hole_points = []
                            for px, py in hole_coords:
                                nx = x + px * thumb_page_scale + thumb_width * 0.05
                                ny = y + (page_h - py) * thumb_page_scale + thumb_height * 0.05
                                hole_points.append((nx, ny))
                            
                            if len(hole_points) >= 3:
                                flat_hole = [coord for point in hole_points for coord in point]
                                canvas.create_polygon(flat_hole, fill='white', outline='black', width=1)
                    
                    if page.geom_type == 'Polygon':
                        draw_thumbnail_polygon(page)
                    elif page.geom_type == 'MultiPolygon':
                        for poly in page.geoms:
                            draw_thumbnail_polygon(poly)
                    
                    # Add page number
                    page_number = row_idx * cols + col_idx + 1
                    canvas.create_text(x + thumb_width / 2, y + thumb_height + 15,
                                       text=f"{page_number}", fill='blue', font=('Arial', 10, 'bold'))
                    
                    # Bind click event
                    canvas.tag_bind(thumb_bg, '<Button-1>', lambda event, idx=page_idx: self.on_thumbnail_click(idx))
                    
                    # Select first page by default
                    if row_idx == 0 and col_idx == 0:
                        canvas.itemconfig(thumb_bg, outline='red', width=3)
                else:
                    # Draw empty placeholder
                    canvas.create_rectangle(x, y, x + thumb_width, y + thumb_height,
                                           fill='white', outline='lightgray', width=1, dash=(2, 2))
        
        # Draw grid lines
        for col in range(cols + 1):
            x = padding + col * (thumb_width + spacing)
            canvas.create_line(x, padding, x, canvas_height - padding - 20, fill='lightgray', dash=(2, 2))
        
        for row in range(rows + 1):
            y = padding + row * (thumb_height + spacing)
            canvas.create_line(padding, y, canvas_width - padding, y, fill='lightgray', dash=(2, 2))
    
    def draw_thumbnails_fallback(self, pages):
        """Fallback thumbnail drawing method"""
        canvas = self.thumbnail_canvas
        canvas.delete('all')
        
        if not pages:
            return
        
        page_size_tuple = PAGE_SIZES[self.config['page_size']]
        page_w, page_h = page_size_tuple
        
        # Thumbnail settings
        thumb_width = 70
        thumb_height = 60
        padding = 10
        spacing = 5
        cols = len(pages)
        rows = 1
        
        canvas_width = cols * (thumb_width + spacing) + padding * 2
        canvas_height = rows * (thumb_height + spacing) + padding * 2 + 20
        canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        thumb_page_scale = min(thumb_width / page_w, thumb_height / page_h) * 0.9
        
        for idx, page in enumerate(pages):
            x = padding + idx * (thumb_width + spacing)
            y = padding
            
            thumb_bg = canvas.create_rectangle(x, y, x + thumb_width, y + thumb_height,
                                               fill='white', outline='gray', width=2, tags=('thumb_bg',))
            
            def draw_thumbnail_polygon(poly):
                exterior_coords = list(poly.exterior.coords)
                points = []
                for px, py in exterior_coords:
                    nx = x + px * thumb_page_scale + thumb_width * 0.05
                    ny = y + (page_h - py) * thumb_page_scale + thumb_height * 0.05
                    points.append((nx, ny))
                
                if len(points) >= 3:
                    flat_points = [coord for point in points for coord in point]
                    canvas.create_polygon(flat_points, fill=self.rgb_to_hex(self.config['primary_color']), 
                                          outline='black', width=1)
                
                for hole in poly.interiors:
                    hole_coords = list(hole.coords)
                    hole_points = []
                    for px, py in hole_coords:
                        nx = x + px * thumb_page_scale + thumb_width * 0.05
                        ny = y + (page_h - py) * thumb_page_scale + thumb_height * 0.05
                        hole_points.append((nx, ny))
                    
                    if len(hole_points) >= 3:
                        flat_hole = [coord for point in hole_points for coord in point]
                        canvas.create_polygon(flat_hole, fill='white', outline='black', width=1)
            
            if page.geom_type == 'Polygon':
                draw_thumbnail_polygon(page)
            elif page.geom_type == 'MultiPolygon':
                for poly in page.geoms:
                    draw_thumbnail_polygon(poly)
            
            canvas.create_text(x + thumb_width / 2, y + thumb_height + 15,
                               text=f"{idx + 1}", fill='blue', font=('Arial', 10, 'bold'))
            
            canvas.tag_bind(thumb_bg, '<Button-1>', lambda event, idx=idx: self.on_thumbnail_click(idx))
            
            if idx == 0:
                canvas.itemconfig(thumb_bg, outline='red', width=3)
    
    def on_thumbnail_click(self, page_idx):
        """Show detailed preview when clicking thumbnail"""
        self.selected_page = page_idx
        
        # Update selection highlight
        canvas = self.thumbnail_canvas
        for item in canvas.find_all():
            tags = canvas.gettags(item)
            if 'thumb_bg' in tags:
                canvas.itemconfig(item, outline='gray', width=2)
        
        # Highlight selected thumbnail
        thumbnails = canvas.find_withtag('thumb_bg')
        if thumbnails:
            canvas.itemconfig(thumbnails[page_idx], outline='red', width=3)
        
        # Update detailed view
        self.draw_detail_preview(self.pages_data[page_idx], page_idx)
    
    def draw_detail_preview(self, page, page_idx):
        """Draw detailed page preview"""
        canvas = self.preview_canvas
        canvas.delete('all')
        
        # Get canvas dimensions
        canvas_w = canvas.winfo_width()
        canvas_h = canvas.winfo_height()
        
        if canvas_w <= 1 or canvas_h <= 1:
            return
        
        # Get bounds
        if page.geom_type == 'Polygon':
            minx, miny, maxx, maxy = page.bounds
        elif page.geom_type == 'MultiPolygon':
            minx, miny, maxx, maxy = page.bounds
        
        page_w = maxx - minx
        page_h = maxy - miny
        
        # Calculate scale to fit preview area
        scale_w = canvas_w / page_w * 0.9
        scale_h = canvas_h / page_h * 0.9
        scale_factor = min(scale_w, scale_h)
        
        # Draw page border
        canvas.create_rectangle(5, 5, canvas_w - 5, canvas_h - 5, outline='gray', dash=(2, 2))
        
        def draw_polygon(poly):
            # Draw exterior
            exterior_coords = list(poly.exterior.coords)
            points = []
            for x, y in exterior_coords:
                nx = (x - minx) * scale_factor + (canvas_w - page_w * scale_factor) / 2
                ny = canvas_h - (y - miny) * scale_factor - (canvas_h - page_h * scale_factor) / 2
                points.append(nx)
                points.append(ny)
            canvas.create_polygon(points, fill=self.rgb_to_hex(self.config['primary_color']), 
                                  outline='black', width=2)
            
            # Draw holes
            for hole in poly.interiors:
                hole_coords = list(hole.coords)
                hole_points = []
                for x, y in hole_coords:
                    nx = (x - minx) * scale_factor + (canvas_w - page_w * scale_factor) / 2
                    ny = canvas_h - (y - miny) * scale_factor - (canvas_h - page_h * scale_factor) / 2
                    hole_points.append(nx)
                    hole_points.append(ny)
                canvas.create_polygon(hole_points, fill='white', outline='black', width=2)
        
        if page.geom_type == 'Polygon':
            draw_polygon(page)
        elif page.geom_type == 'MultiPolygon':
            for poly in page.geoms:
                draw_polygon(poly)
        
        # Add page info
        canvas.create_text(canvas_w / 2, canvas_h - 15, 
                          text=f"Page {page_idx + 1} / {len(self.pages_data)}", fill='gray')
    
    def rgb_to_hex(self, rgb):
        """Convert RGB to hex color"""
        return '#%02x%02x%02x' % tuple(int(v * 255) for v in rgb)

if __name__ == "__main__":
    root = tk.Tk()
    app = BigFontPrintApp(root)
    root.mainloop()
