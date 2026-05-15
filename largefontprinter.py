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

# ==================== 数据结构定义 ====================
"""
ContourPoint: 2D坐标点，tuple[float, float]
RawContour: 原始轮廓数据，list[ContourPoint]
ProcessedPolygon: 处理后的多边形结构 {
    "polygon": shapely.Polygon,
    "is_outer": bool,   # 是否外轮廓
    "children": list    # 嵌套子轮廓
}
"""

# ==================== 自定义异常 ====================
class FontProcessingError(Exception):
    """字体处理专用异常"""
    def __init__(self, message):
        super().__init__(f"字体处理错误: {message}")

# ==================== 填充样式定义 ====================
FILL_STYLES = {
    'solid': '纯色填充',
    'horizontal': '水平渐变',
    'vertical': '垂直渐变',
    'radial': '径向渐变',
    'crosshatch': '交叉阴影',
    'dots': '圆点图案',
    'lines': '平行线图案',
    'grid': '网格图案'
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

# ==================== 轮廓采集笔 ====================
class ContourPen(BasePen):
    """字体轮廓采集工具（继承自BasePen）"""
    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.contours = []
        self.current_contour = []

    def _moveTo(self, pt):
        """开始新轮廓路径"""
        self.current_contour = [pt]

    def _lineTo(self, pt):
        """绘制直线到指定点"""
        self.current_contour.append(pt)

    def cubic_bezier(self, t, P0, P1, P2, P3):
        """计算三次贝塞尔曲线上的点"""
        x = (1 - t) ** 3 * P0[0] + 3 * (1 - t) ** 2 * t * P1[0] + 3 * (1 - t) * t ** 2 * P2[0] + t ** 3 * P3[0]
        y = (1 - t) ** 3 * P0[1] + 3 * (1 - t) ** 2 * t * P1[1] + 3 * (1 - t) * t ** 2 * P2[1] + t ** 3 * P3[1]
        return (x, y)

    def _curveToOne(self, pt1, pt2, pt3):
        """处理三次贝塞尔曲线"""
        p0 = self.current_contour[-1]
        t_values = np.linspace(0, 1, 100)
        curve_points = [self.cubic_bezier(t, p0, pt1, pt2, pt3) for t in t_values]
        self.current_contour.extend(curve_points)

    def _closePath(self):
        """闭合当前轮廓路径"""
        if len(self.current_contour) > 0:
            self.contours.append(self.current_contour)
            self.current_contour = []

# ==================== 字形处理器 ====================
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
        """应用仿射变换"""
        return [tuple(np.dot(matrix, (x, y, 1))[:2]) for x, y in points]

    def build_contour_hierarchy(self, contours):
        """构建带孔洞的层级结构"""
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
        """构建几何形状"""
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
        """动态分页处理"""
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
        
        # 返回一个包含所有信息的自定义对象
        class PageList(list):
            def __init__(self, pages, total_bounds, page_info):
                super().__init__(pages)
                self.total_bounds = total_bounds
                self.page_info = page_info
        
        # 构建页面信息列表
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
        """坐标转换到页面局部坐标系"""
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

# ==================== PDF生成器（支持多种填充方式） ====================
class PDFGenerator:
    def __init__(self, filename, page_size):
        self.canvas = canvas.Canvas(filename, pagesize=page_size)
        self.page_w, self.page_h = page_size

    def render(self, pages, fill_style='solid', color=(1, 0, 0), 
               second_color=(0, 0, 1), pattern_density=10):
        """
        渲染PDF页面
        :param pages: 页面几何数据列表
        :param fill_style: 填充样式
        :param color: 主颜色 (RGB 0-1)
        :param second_color: 次要颜色（用于渐变）
        :param pattern_density: 图案密度
        """
        for idx, page in enumerate(pages):
            if idx > 0:
                self.canvas.showPage()
            self._draw_page(page, fill_style, color, second_color, pattern_density)
        self.canvas.save()

    def _draw_page(self, geometry, fill_style, color, second_color, pattern_density):
        """绘制单个页面"""
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
        """渲染单个多边形"""
        self._add_contour(path, polygon.exterior)
        for hole in polygon.interiors:
            self._add_contour(path, hole)

    def _add_contour(self, path, ring):
        """添加轮廓路径"""
        coords = list(ring.coords)
        path.moveTo(*coords[0])
        for pt in coords[1:]:
            path.lineTo(*pt)
        path.close()

    def _apply_fill(self, fill_style, color, second_color, pattern_density):
        """应用填充样式"""
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
        """应用图案填充"""
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

# ==================== 图形界面 ====================
class BigFontPrintApp:
    def __init__(self, root):
        self.root = root
        self.root.title("特大字分页打印系统")
        self.root.geometry("900x700")
        
        # 默认配置
        self.config = {
            'font_path': '',
            'char': '回',
            'scale_factor': 5,
            'page_size': 'A4',
            'output_file': 'output.pdf',
            'fill_style': 'solid',
            'primary_color': (1.0, 0.0, 0.0),  # 红色
            'secondary_color': (0.0, 0.0, 1.0),  # 蓝色
            'pattern_density': 10
        }
        
        # 创建GUI
        self.create_widgets()
        
    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧控制面板
        left_panel = ttk.Frame(main_frame, width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # 右侧预览区域
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # ========== 左侧控制面板 ==========
        
        # 字体选择
        ttk.Label(left_panel, text="字体文件:").pack(anchor=tk.W, pady=(10, 2))
        font_frame = ttk.Frame(left_panel)
        font_frame.pack(fill=tk.X)
        self.font_path_entry = ttk.Entry(font_frame)
        self.font_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(font_frame, text="浏览", command=self.browse_font).pack(side=tk.RIGHT)
        
        # 字符输入
        ttk.Label(left_panel, text="输入字符:").pack(anchor=tk.W, pady=(10, 2))
        self.char_entry = ttk.Entry(left_panel, font=('Arial', 20))
        self.char_entry.insert(0, '回')
        self.char_entry.pack(fill=tk.X)
        
        # 缩放比例
        ttk.Label(left_panel, text="缩放比例:").pack(anchor=tk.W, pady=(10, 2))
        self.scale_label = ttk.Label(left_panel, text="5.0x")
        self.scale_slider = ttk.Scale(left_panel, from_=1, to=20, orient=tk.HORIZONTAL, 
                                      command=self.update_scale_label)
        self.scale_slider.set(5)
        self.scale_slider.pack(fill=tk.X)
        self.scale_label.pack(anchor=tk.W)
        
        # 页面大小
        ttk.Label(left_panel, text="页面大小:").pack(anchor=tk.W, pady=(10, 2))
        self.page_size_combobox = ttk.Combobox(left_panel, values=list(PAGE_SIZES.keys()))
        self.page_size_combobox.set('A4')
        self.page_size_combobox.pack(fill=tk.X)
        
        # 填充样式
        ttk.Label(left_panel, text="填充样式:").pack(anchor=tk.W, pady=(10, 2))
        self.fill_style_combobox = ttk.Combobox(left_panel, values=list(FILL_STYLES.values()))
        self.fill_style_combobox.set('纯色填充')
        self.fill_style_combobox.bind('<<ComboboxSelected>>', self.update_fill_options)
        self.fill_style_combobox.pack(fill=tk.X)
        
        # 主颜色
        ttk.Label(left_panel, text="主颜色:").pack(anchor=tk.W, pady=(10, 2))
        color_frame = ttk.Frame(left_panel)
        color_frame.pack(fill=tk.X)
        self.color_button = ttk.Button(color_frame, text="选择颜色", command=self.choose_primary_color)
        self.color_button.pack(side=tk.LEFT)
        self.color_preview = ttk.Label(color_frame, width=10, background='#FF0000')
        self.color_preview.pack(side=tk.RIGHT)
        
        # 次要颜色（渐变用）
        self.secondary_color_frame = ttk.Frame(left_panel)
        ttk.Label(self.secondary_color_frame, text="次要颜色:").pack(anchor=tk.W)
        color2_frame = ttk.Frame(self.secondary_color_frame)
        color2_frame.pack(fill=tk.X)
        self.color2_button = ttk.Button(color2_frame, text="选择颜色", command=self.choose_secondary_color)
        self.color2_button.pack(side=tk.LEFT)
        self.color2_preview = ttk.Label(color2_frame, width=10, background='#0000FF')
        self.color2_preview.pack(side=tk.RIGHT)
        self.secondary_color_frame.pack(fill=tk.X)
        
        # 图案密度
        self.pattern_density_frame = ttk.Frame(left_panel)
        ttk.Label(self.pattern_density_frame, text="图案密度:").pack(anchor=tk.W, pady=(10, 2))
        self.density_label = ttk.Label(self.pattern_density_frame, text="10")
        self.density_slider = ttk.Scale(self.pattern_density_frame, from_=5, to=50, orient=tk.HORIZONTAL,
                                        command=self.update_density_label)
        self.density_slider.set(10)
        self.density_slider.pack(fill=tk.X)
        self.density_label.pack(anchor=tk.W)
        self.pattern_density_frame.pack(fill=tk.X)
        
        # 输出文件
        ttk.Label(left_panel, text="输出文件:").pack(anchor=tk.W, pady=(10, 2))
        output_frame = ttk.Frame(left_panel)
        output_frame.pack(fill=tk.X)
        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.insert(0, 'output.pdf')
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(output_frame, text="浏览", command=self.browse_output).pack(side=tk.RIGHT)
        
        # 生成按钮
        ttk.Button(left_panel, text="生成PDF", command=self.generate_pdf, style='Accent.TButton').pack(
            fill=tk.X, pady=20)
        
        # 进度标签
        self.status_label = ttk.Label(left_panel, text="就绪", foreground='green')
        self.status_label.pack(anchor=tk.W)
        
        # ========== 右侧预览区域 ==========
        # 页面缩略图区域（拼图布局）
        ttk.Label(right_panel, text="页面布局预览（点击查看详情）").pack(anchor=tk.W, pady=5)
        self.thumbnail_frame = ttk.Frame(right_panel)
        self.thumbnail_frame.pack(fill=tk.X)
        
        # 添加水平滚动条
        self.thumbnail_hscrollbar = ttk.Scrollbar(self.thumbnail_frame, orient=tk.HORIZONTAL)
        self.thumbnail_hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 添加垂直滚动条
        self.thumbnail_vscrollbar = ttk.Scrollbar(self.thumbnail_frame, orient=tk.VERTICAL)
        self.thumbnail_vscrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 添加滚动条容器（支持双向滚动）
        self.thumbnail_canvas = tk.Canvas(self.thumbnail_frame, bg='lightgray', height=180, 
                                          scrollregion=(0, 0, 1000, 1000),
                                          xscrollcommand=self.thumbnail_hscrollbar.set,
                                          yscrollcommand=self.thumbnail_vscrollbar.set)
        self.thumbnail_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 配置滚动条
        self.thumbnail_hscrollbar.configure(command=self.thumbnail_canvas.xview)
        self.thumbnail_vscrollbar.configure(command=self.thumbnail_canvas.yview)
        
        # 详细预览区域
        ttk.Label(right_panel, text="详细预览").pack(anchor=tk.W, pady=5)
        self.preview_canvas = tk.Canvas(right_panel, bg='white', relief=tk.SUNKEN, borderwidth=2)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # 保存页面数据
        self.pages_data = []
        self.selected_page = 0
        
        # 更新填充选项显示
        self.update_fill_options()
    
    def browse_font(self):
        """浏览字体文件"""
        path = filedialog.askopenfilename(filetypes=[('TrueType字体', '*.ttf'), ('OpenType字体', '*.otf')])
        if path:
            self.font_path_entry.delete(0, tk.END)
            self.font_path_entry.insert(0, path)
    
    def browse_output(self):
        """浏览输出文件"""
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF文件', '*.pdf')])
        if path:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, path)
    
    def choose_primary_color(self):
        """选择主颜色"""
        color = colorchooser.askcolor(title="选择主颜色")
        if color[1]:
            self.config['primary_color'] = self.hex_to_rgb(color[1])
            self.color_preview.config(background=color[1])
    
    def choose_secondary_color(self):
        """选择次要颜色"""
        color = colorchooser.askcolor(title="选择次要颜色")
        if color[1]:
            self.config['secondary_color'] = self.hex_to_rgb(color[1])
            self.color2_preview.config(background=color[1])
    
    def hex_to_rgb(self, hex_color):
        """将十六进制颜色转换为RGB (0-1)"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    
    def update_scale_label(self, value):
        """更新缩放比例标签"""
        self.scale_label.config(text=f"{float(value):.1f}x")
    
    def update_density_label(self, value):
        """更新图案密度标签"""
        self.density_label.config(text=f"{int(float(value))}")
    
    def update_fill_options(self, event=None):
        """根据填充样式显示/隐藏相关选项"""
        style_name = self.fill_style_combobox.get()
        style_key = list(FILL_STYLES.keys())[list(FILL_STYLES.values()).index(style_name)]
        
        # 显示/隐藏次要颜色选择（渐变需要）
        if style_key in ['horizontal', 'vertical', 'radial']:
            self.secondary_color_frame.pack(fill=tk.X)
        else:
            self.secondary_color_frame.pack_forget()
        
        # 显示/隐藏图案密度（图案填充需要）
        if style_key in ['crosshatch', 'dots', 'lines', 'grid']:
            self.pattern_density_frame.pack(fill=tk.X)
        else:
            self.pattern_density_frame.pack_forget()
    
    def generate_pdf(self):
        """生成PDF"""
        try:
            # 获取配置
            self.config['font_path'] = self.font_path_entry.get()
            self.config['char'] = self.char_entry.get()
            self.config['scale_factor'] = float(self.scale_slider.get())
            self.config['page_size'] = self.page_size_combobox.get()
            self.config['output_file'] = self.output_entry.get()
            
            style_name = self.fill_style_combobox.get()
            self.config['fill_style'] = list(FILL_STYLES.keys())[list(FILL_STYLES.values()).index(style_name)]
            self.config['pattern_density'] = int(self.density_slider.get())
            
            # 验证输入
            if not self.config['font_path']:
                messagebox.showerror("错误", "请选择字体文件")
                return
            
            if not self.config['char']:
                messagebox.showerror("错误", "请输入字符")
                return
            
            if len(self.config['char']) > 1:
                messagebox.showerror("错误", "请只输入一个字符")
                return
            
            # 更新状态
            self.status_label.config(text="正在处理...", foreground='orange')
            self.root.update()
            
            # 处理字形
            page_size_tuple = PAGE_SIZES[self.config['page_size']]
            processor = GlyphProcessor(
                self.config['font_path'],
                self.config['char'],
                self.config['scale_factor'],
                page_size_tuple
            )
            pages = processor.process()
            
            if not pages:
                messagebox.showwarning("警告", "没有生成任何页面")
                self.status_label.config(text="就绪", foreground='green')
                return
            
            # 生成PDF
            pdf_gen = PDFGenerator(self.config['output_file'], page_size_tuple)
            pdf_gen.render(
                pages,
                fill_style=self.config['fill_style'],
                color=self.config['primary_color'],
                second_color=self.config['secondary_color'],
                pattern_density=self.config['pattern_density']
            )
            
            # 更新预览
            self.update_preview(pages)
            
            # 更新状态
            self.status_label.config(text=f"生成成功！共 {len(pages)} 页", foreground='green')
            messagebox.showinfo("成功", f"PDF生成成功！共 {len(pages)} 页")
            
        except Exception as e:
            self.status_label.config(text=f"失败: {str(e)}", foreground='red')
            messagebox.showerror("错误", f"生成失败: {str(e)}")
    
    def update_preview(self, pages):
        """更新预览，包括缩略图和详细视图"""
        if not pages:
            return
        
        # 保存页面数据
        self.pages_data = pages
        self.selected_page = 0
        
        # 先绘制缩略图
        self.draw_thumbnails(pages)
        
        # 再绘制详细预览
        self.draw_detail_preview(pages[0], 0)
    
    def draw_thumbnails(self, pages):
        """绘制页面缩略图（方形网格布局）"""
        canvas = self.thumbnail_canvas
        canvas.delete('all')
        
        if not pages:
            return
        
        # 获取页面大小
        page_size_tuple = PAGE_SIZES[self.config['page_size']]
        page_w, page_h = page_size_tuple
        
        # 获取分页时保存的额外信息
        page_info_list = getattr(pages, 'page_info', [])
        total_bounds = getattr(pages, 'total_bounds', None)
        
        if not page_info_list or total_bounds is None:
            # 如果没有保存额外信息，使用传统方法
            self.draw_thumbnails_fallback(pages)
            return
        
        minx_all, miny_all, maxx_all, maxy_all = total_bounds
        
        # 计算分页行列数
        cols = int((maxx_all - minx_all) / page_w) + 1
        rows = int((maxy_all - miny_all) / page_h) + 1
        
        # 确保至少有1行1列
        cols = max(cols, 1)
        rows = max(rows, 1)
        
        # 缩略图尺寸
        thumb_width = 70
        thumb_height = 60
        padding = 10
        spacing = 5
        
        # 计算画布尺寸
        canvas_width = cols * (thumb_width + spacing) + padding * 2
        canvas_height = rows * (thumb_height + spacing) + padding * 2 + 20
        canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        # 计算页面在缩略图中的缩放比例
        thumb_page_scale_w = thumb_width / page_w * 0.9
        thumb_page_scale_h = thumb_height / page_h * 0.9
        thumb_page_scale = min(thumb_page_scale_w, thumb_page_scale_h)
        
        # 为每个网格位置创建页面映射
        grid = {}
        for info in page_info_list:
            col_idx = info['col']
            row_idx = info['row']
            grid[(row_idx, col_idx)] = info
        
        # 按行优先顺序绘制每个缩略图
        for row_idx in range(rows):
            for col_idx in range(cols):
                # 计算缩略图位置
                x = padding + col_idx * (thumb_width + spacing)
                y = padding + row_idx * (thumb_height + spacing)
                
                # 检查是否有对应的页面数据
                key = (row_idx, col_idx)
                if key in grid:
                    info = grid[key]
                    page = info['page']
                    page_idx = page_info_list.index(info)  # 获取原始索引
                    page_minx, page_miny, page_maxx, page_maxy = info['original_bounds']
                    
                    # 创建缩略图背景（带边框）
                    thumb_bg = canvas.create_rectangle(x, y, x + thumb_width, y + thumb_height,
                                                       fill='white', outline='gray', width=2, tags=('thumb_bg',))
                    
                    # 绘制该页面的字形内容（页面坐标已经是局部坐标，从0开始）
                    def draw_thumbnail_polygon(poly):
                        # 获取多边形的所有坐标点（已经是页面局部坐标）
                        exterior_coords = list(poly.exterior.coords)
                        
                        # 将页面局部坐标转换到缩略图坐标
                        points = []
                        for px, py in exterior_coords:
                            nx = x + px * thumb_page_scale + thumb_width * 0.05
                            ny = y + (page_h - py) * thumb_page_scale + thumb_height * 0.05
                            points.append((nx, ny))
                        
                        # 绘制多边形（需要至少3个点）
                        if len(points) >= 3:
                            flat_points = [coord for point in points for coord in point]
                            canvas.create_polygon(flat_points, fill=self.rgb_to_hex(self.config['primary_color']), 
                                                  outline='black', width=1)
                        
                        # 绘制孔洞
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
                    
                    # 添加页码标签
                    page_number = row_idx * cols + col_idx + 1
                    canvas.create_text(x + thumb_width / 2, y + thumb_height + 15,
                                       text=f"{page_number}", fill='blue', font=('Arial', 10, 'bold'))
                    
                    # 绑定点击事件
                    canvas.tag_bind(thumb_bg, '<Button-1>', lambda event, idx=page_idx: self.on_thumbnail_click(idx))
                    
                    # 默认选中第一个页面（左上角）
                    if row_idx == 0 and col_idx == 0:
                        canvas.itemconfig(thumb_bg, outline='red', width=3)
                else:
                    # 绘制空白占位
                    canvas.create_rectangle(x, y, x + thumb_width, y + thumb_height,
                                           fill='white', outline='lightgray', width=1, dash=(2, 2))
        
        # 添加网格线
        for col in range(cols + 1):
            x = padding + col * (thumb_width + spacing)
            canvas.create_line(x, padding, x, canvas_height - padding - 20, fill='lightgray', dash=(2, 2))
        
        for row in range(rows + 1):
            y = padding + row * (thumb_height + spacing)
            canvas.create_line(padding, y, canvas_width - padding, y, fill='lightgray', dash=(2, 2))
    
    def draw_thumbnails_fallback(self, pages):
        """回退方法：当没有额外信息时使用传统方式绘制缩略图"""
        canvas = self.thumbnail_canvas
        canvas.delete('all')
        
        if not pages:
            return
        
        page_size_tuple = PAGE_SIZES[self.config['page_size']]
        page_w, page_h = page_size_tuple
        
        # 绘制所有页面的缩略图，按顺序排列
        thumb_width = 70
        thumb_height = 60
        padding = 10
        spacing = 5
        cols = len(pages)
        rows = 1
        
        canvas_width = cols * (thumb_width + spacing) + padding * 2
        canvas_height = rows * (thumb_height + spacing) + padding * 2 + 20
        canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        thumb_page_scale_w = thumb_width / page_w * 0.9
        thumb_page_scale_h = thumb_height / page_h * 0.9
        thumb_page_scale = min(thumb_page_scale_w, thumb_page_scale_h)
        
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
        """点击缩略图时显示详细预览"""
        self.selected_page = page_idx
        
        # 更新缩略图选中状态
        canvas = self.thumbnail_canvas
        for item in canvas.find_all():
            tags = canvas.gettags(item)
            if 'thumb_bg' in tags:
                canvas.itemconfig(item, outline='gray', width=2)
        
        # 高亮选中的缩略图
        thumbnails = canvas.find_withtag('thumb_bg')
        if thumbnails:
            canvas.itemconfig(thumbnails[page_idx], outline='red', width=3)
        
        # 更新详细预览
        self.draw_detail_preview(self.pages_data[page_idx], page_idx)
    
    def draw_detail_preview(self, page, page_idx):
        """绘制详细预览"""
        canvas = self.preview_canvas
        
        # 清空画布
        canvas.delete('all')
        
        # 获取画布尺寸
        canvas_w = canvas.winfo_width()
        canvas_h = canvas.winfo_height()
        
        if canvas_w <= 1 or canvas_h <= 1:
            return
        
        # 获取页面边界
        if page.geom_type == 'Polygon':
            minx, miny, maxx, maxy = page.bounds
        elif page.geom_type == 'MultiPolygon':
            minx, miny, maxx, maxy = page.bounds
        
        page_w = maxx - minx
        page_h = maxy - miny
        
        # 计算缩放比例以适应预览区域
        scale_w = canvas_w / page_w * 0.9
        scale_h = canvas_h / page_h * 0.9
        scale_factor = min(scale_w, scale_h)
        
        # 绘制页面边框
        canvas.create_rectangle(5, 5, canvas_w - 5, canvas_h - 5, outline='gray', dash=(2, 2))
        
        def draw_polygon(poly, color='red'):
            # 绘制外轮廓
            exterior_coords = list(poly.exterior.coords)
            points = []
            for x, y in exterior_coords:
                nx = (x - minx) * scale_factor + (canvas_w - page_w * scale_factor) / 2
                ny = canvas_h - (y - miny) * scale_factor - (canvas_h - page_h * scale_factor) / 2
                points.append(nx)
                points.append(ny)
            canvas.create_polygon(points, fill=self.rgb_to_hex(self.config['primary_color']), 
                                  outline='black', width=2)
            
            # 绘制孔洞
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
        
        # 添加页数信息
        canvas.create_text(canvas_w / 2, canvas_h - 15, 
                          text=f"第 {page_idx + 1} / {len(self.pages_data)} 页", fill='gray')
    
    def rgb_to_hex(self, rgb):
        """将RGB转换为十六进制"""
        return '#%02x%02x%02x' % tuple(int(v * 255) for v in rgb)

if __name__ == "__main__":
    root = tk.Tk()
    app = BigFontPrintApp(root)
    root.mainloop()