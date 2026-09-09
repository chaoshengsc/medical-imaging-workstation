"""离线帮助阅读器：目录、段落搜索、阅读历史与隔离的教学图解。"""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from help_topics import TOPICS, search_topics


class WindowMappingPlot(QWidget):
    """归一化强度示意，完全独立于主窗影像和窗位控件。"""

    def __init__(self, english=False):
        super().__init__()
        self.english = english
        self.width_value, self.level_value = 45, 50
        self.setMinimumHeight(205)
        self.setAccessibleName('Schematic intensity-to-grey mapping' if english else '强度到显示灰度的教学示意')

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(32, 18, max(100, self.width() - 48), 108)
        low, high = self.level_value - self.width_value / 2, self.level_value + self.width_value / 2
        p.setPen(QPen(QColor('#64748B'), 1)); p.drawRect(r)
        path = QPainterPath()
        for i in range(101):
            value = min(1, max(0, (i - low) / (high - low)))
            point = QPointF(r.left() + i / 100 * r.width(), r.bottom() - value * r.height())
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
            grey = round(value * 255)
            p.fillRect(QRectF(r.left() + i / 101 * r.width(), 158, r.width() / 101 + 1, 18), QColor(grey, grey, grey))
        p.setPen(QPen(QColor('#69D2D8'), 2)); p.drawPath(path)
        p.setPen(QColor('#D1D5DB'))
        p.drawText(QRectF(0, 12, 26, 24), Qt.AlignRight, '1')
        p.drawText(QRectF(0, 108, 26, 24), Qt.AlignRight, '0')
        p.drawText(QRectF(32, 130, r.width(), 24), Qt.AlignCenter,
                   'Input intensity 0 → 100' if self.english else '输入强度 0 → 100（归一化示意）')
        p.drawText(QRectF(32, 180, r.width(), 22), Qt.AlignCenter,
                   'Displayed grey' if self.english else '对应的显示灰度')
        p.end()


class HelpDiagram(QWidget):
    """图示使用原生控件换行；交互只改变帮助窗口内的示例。"""

    def __init__(self, kind, english=False):
        super().__init__()
        self.setObjectName('HelpDiagram'); self.english = int(english)
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(10)

        def label(pair, box=False):
            w = QLabel(pair[self.english]); w.setWordWrap(True); w.setTextFormat(Qt.PlainText)
            w.setAlignment(Qt.AlignCenter)
            if box:
                w.setObjectName('DiagramNode')
            return w

        if kind == 'window':
            layout.addWidget(label(('独立教学示例 · 不改变当前影像', 'Isolated teaching example · current image unchanged')))
            self.plot = WindowMappingPlot(english); layout.addWidget(self.plot)
            self.width_slider = QSlider(Qt.Horizontal); self.width_slider.setRange(5, 100); self.width_slider.setValue(45)
            self.level_slider = QSlider(Qt.Horizontal); self.level_slider.setRange(0, 100); self.level_slider.setValue(50)
            self.width_slider.setAccessibleName('Example width' if english else '示例窗宽')
            self.level_slider.setAccessibleName('Example level' if english else '示例窗位')
            self.values = label(('', '')); layout.addWidget(self.values)
            for title, slider in ((('W · 示例窗宽', 'W · Example width'), self.width_slider),
                                  (('L · 示例窗位', 'L · Example level'), self.level_slider)):
                row = QHBoxLayout(); row.addWidget(label(title)); row.addWidget(slider, 1); layout.addLayout(row)
                slider.valueChanged.connect(self._update_mapping)
            self._update_mapping()
            layout.addWidget(label(('曲线表示强度如何映射到灰度。试着缩小 W：灰度过渡会变陡。这里使用简化连续映射，不是当前 DICOM 的测量值。',
                                    'The curve maps intensity to grey. Reduce W to steepen the transition. This is a simplified continuous mapping, not measurements from the current DICOM.')))
        elif kind == 'recon':
            layout.addWidget(label(('FBP 对比：四个视图区分别显示什么？', 'FBP comparison: what do the four views show?')))
            grid = QGridLayout()
            for row, col, pair in (
                (0, 0, ('V1 · 来源\n模体或输入图像', 'V1 · Source\nPhantom or input image')),
                (0, 2, ('V2 · 弦图\n横轴角度 · 纵轴探测器位置', 'V2 · Sinogram\nHorizontal: angle\nVertical: detector position')),
                (2, 0, ('V3 · BP\n未滤波反投影', 'V3 · BP\nUnfiltered back-projection')),
                (2, 2, ('V4 · FBP\n滤波后反投影', 'V4 · FBP\nFiltered back-projection')),
            ):
                grid.addWidget(label(pair, True), row, col)
            grid.addWidget(label(('→', '→')), 0, 1)
            grid.addWidget(label(('↓ 同一 V2 弦图分别输入 BP 与 FBP ↓', '↓ The same V2 sinogram feeds BP and FBP ↓')), 1, 0, 1, 3)
            grid.setColumnStretch(0, 1); grid.setColumnStretch(2, 1); layout.addLayout(grid)
            layout.addWidget(label(('此对应关系用于 FBP 对比；切换其他算法后以实际视图标题为准。',
                                    'This layout describes FBP comparison. For other algorithms, follow the actual view titles.')))
        elif kind == 'layers':
            layout.addWidget(label(('显示哪个图层，与统计哪个结果要分别确认', 'Confirm the displayed layer and measured result separately')))
            grid = QGridLayout()
            grid.addWidget(label(('原始 AI 结果\n只读保留', 'Original AI result\nRead-only'), True), 0, 0)
            grid.addWidget(label(('→', '→')), 0, 1)
            grid.addWidget(label(('原始 AI 对照\n只改变显示', 'Original AI comparison\nDisplay only'), True), 0, 2)
            grid.addWidget(label(('↓ 采用到工作图层', '↓ Adopt into working layer')), 1, 0)
            grid.addWidget(label(('工作图层\n人工编辑 · Undo', 'Working layer\nManual edits · Undo'), True), 2, 0)
            grid.addWidget(label(('→', '→')), 2, 1)
            grid.addWidget(label(('工作结果统计\nCSV / 三维（条件满足时）', 'Working-result statistics\nCSV / 3D when eligible'), True), 2, 2)
            grid.setColumnStretch(0, 1); grid.setColumnStretch(2, 1); layout.addLayout(grid)
            layout.addWidget(label(('看见原始 AI 对照，不代表下方统计已经切换到原始 AI。查看结果来源标签。',
                                    'Viewing original AI does not switch the statistics to original AI. Check the result-source label.')))

    def _update_mapping(self):
        self.plot.width_value = self.width_slider.value(); self.plot.level_value = self.level_slider.value()
        self.values.setText(f'W = {self.plot.width_value}     L = {self.plot.level_value}')
        self.plot.update()


class HelpCenter(QDialog):
    """独立非模态窗口；导航只保存阅读状态，绝不切换主窗功能。"""

    def __init__(self, parent, english=False, context_provider=None):
        super().__init__(parent, Qt.Window)
        self.setModal(False)
        self.english = int(english); self.context_provider = context_provider
        self.topic_id = None; self.sections = []; self._history = []; self._history_index = -1
        self._render_revision = 0; self._compact = None
        self.resize(940, 720); self.setMinimumSize(430, 380)
        self.setWindowTitle(self.tr_text(('帮助与学习', 'Help and learning')))
        self.setStyleSheet('''
            QDialog, QScrollArea, QWidget#HelpContent { background: #12141A; }
            QLabel { color: #D1D5DB; font-size: 14px; }
            QLabel#HelpTitle { color: #E2E8F0; font-size: 24px; font-weight: bold; }
            QLabel#HelpMeta { color: #AAB8CB; font-size: 12px; }
            QWidget#HelpDiagram { background: #1C1F26; border: 1px solid #475569; border-radius: 6px; }
            QLabel#DiagramNode { color: #E2E8F0; background: #222C37; border: 1px solid #64748B; border-radius: 4px; padding: 10px; }
            QLineEdit { background: #1C1F26; color: #E2E8F0; border: 1px solid #64748B; padding: 8px; }
            QToolButton { color: #BDE5E7; background: #1C1F26; border: 1px solid #4B5563; padding: 10px; font-size: 14px; }
            QToolButton:focus, QLineEdit:focus, QListWidget:focus, QTreeWidget:focus { border: 1px solid #69D2D8; }
            QToolButton:checked, QPushButton:checked { background: #174C52; }
            QTreeWidget, QListWidget { background: #171C24; color: #D1D5DB; border: 1px solid #374151; font-size: 13px; }
            QTreeWidget::item, QListWidget::item { padding: 8px 5px; }
            QTreeWidget::item:selected, QListWidget::item:selected { color: #E2E8F0; background: #174C52; }
            QScrollBar:vertical { background: #171C24; width: 10px; }
            QScrollBar::handle:vertical { background: #64748B; min-height: 24px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        ''')
        layout = QVBoxLayout(self); layout.setContentsMargins(18, 16, 18, 14); layout.setSpacing(10)
        nav = QHBoxLayout()
        self.back_button = self._button(('← 返回', '← Back'), self.go_back)
        self.forward_button = self._button(('前进 →', 'Forward →'), self.go_forward)
        self.catalog_button = self._button(('目录', 'Contents'), self._toggle_catalog)
        self.catalog_button.setCheckable(True); self.catalog_button.setChecked(True)
        self.current_button = self._button(('查看当前功能', 'Current function'), self.show_context)
        for button in (self.back_button, self.forward_button, self.catalog_button):
            nav.addWidget(button)
        nav.addStretch(); nav.addWidget(self.current_button); layout.addLayout(nav)
        self.search = QLineEdit(); self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(self.tr_text(('搜索操作、参数或问题，例如：导出、HU、无法标注', 'Search tasks, parameters or problems: export, HU, annotation')))
        self.search.setAccessibleName(self.tr_text(('搜索帮助全文', 'Search all help text')))
        palette = self.search.palette(); palette.setColor(QPalette.PlaceholderText, QColor('#AAB8CB')); self.search.setPalette(palette)
        layout.addWidget(self.search)
        self.splitter = QSplitter(Qt.Horizontal); self.splitter.setChildrenCollapsible(False)
        self.sidebar = QWidget(); side = QVBoxLayout(self.sidebar); side.setContentsMargins(0, 0, 0, 0); side.setSpacing(6)
        self.directory = QTreeWidget(); self.directory.setHeaderHidden(True); self.directory.setIndentation(12)
        self.directory.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.directory.setAccessibleName(self.tr_text(('按任务浏览帮助目录', 'Help contents by task')))
        self.directory.setMinimumWidth(180)
        groups = {}; self.topic_items = {}
        for key, topic in TOPICS.items():
            group = self.tr_text(topic['group'])
            if group not in groups:
                item = QTreeWidgetItem(self.directory, [group]); item.setFlags(Qt.ItemIsEnabled)
                groups[group] = item
            item = QTreeWidgetItem(groups[group], [self.tr_text(topic['title'])]); item.setData(0, Qt.UserRole, key)
            self.topic_items[key] = item
        self.directory.expandAll(); self.directory.itemClicked.connect(self._directory_activated)
        self.directory.itemActivated.connect(self._directory_activated)
        side.addWidget(self.directory, 1)
        self.result_count = QLabel(); self.result_count.setObjectName('HelpMeta'); self.result_count.setWordWrap(True); self.result_count.hide()
        side.addWidget(self.result_count)
        self.results = QListWidget(); self.results.setWordWrap(True)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.ElideNone); self.results.setMinimumWidth(180)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setAccessibleName(self.tr_text(('搜索结果：主题、小节和匹配摘要', 'Search results: topic, section and excerpt')))
        self.results.itemClicked.connect(self._result_activated); self.results.itemActivated.connect(self._result_activated)
        self.results.hide(); side.addWidget(self.results, 1)
        self.directory.installEventFilter(self); self.results.installEventFilter(self)
        self.no_results = QLabel(self.tr_text(('没有找到匹配内容。试试较短的词，如“保存”或“投影”；清空搜索可返回目录。',
                                             'No matching content. Try a shorter term such as “save” or “projection”; clear search for contents.')))
        self.no_results.setWordWrap(True); self.no_results.hide(); side.addWidget(self.no_results)
        self.splitter.addWidget(self.sidebar)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setMinimumWidth(220); self.splitter.addWidget(self.scroll)
        self.splitter.setStretchFactor(1, 1); self.splitter.setSizes([220, 650]); layout.addWidget(self.splitter, 1)
        footer = QHBoxLayout()
        note = QLabel(self.tr_text(('教学与科研 · 帮助不会改变当前工作区', 'Teaching and research · Help leaves your workspace unchanged')))
        note.setObjectName('HelpMeta'); note.setWordWrap(True); footer.addWidget(note, 1)
        footer.addWidget(self._button(('关闭', 'Close'), self.close)); layout.addLayout(footer)
        self.search.textChanged.connect(self.filter_topics)
        self.search.returnPressed.connect(self._activate_first_result)
        self._update_history_buttons()

    def tr_text(self, pair):
        return pair[self.english]

    def _button(self, pair, callback):
        button = QPushButton(self.tr_text(pair)); button.setAutoDefault(False)
        button.clicked.connect(callback)
        return button

    def _directory_activated(self, item, column=0):
        key = item.data(0, Qt.UserRole)
        if key:
            self.select_topic(key); self._finish_navigation()

    def _result_activated(self, item):
        key, section = item.data(Qt.UserRole)
        self.select_topic(key, section, force=True); self._finish_navigation()

    def _activate_first_result(self):
        if self.search.text().strip() and self.results.count():
            self._result_activated(self.results.currentItem() or self.results.item(0))

    def eventFilter(self, watched, event):
        # Cocoa 的列表 Return 不一定发 itemActivated；明确支持键盘打开选中项。
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = watched.currentItem() if watched in (self.directory, self.results) else None
            if item is not None:
                if watched is self.results:
                    self._result_activated(item)
                elif item.data(0, Qt.UserRole):
                    self._directory_activated(item)
                else:
                    item.setExpanded(not item.isExpanded())
                return True
        return super().eventFilter(watched, event)

    def _finish_navigation(self):
        if self._compact:
            self.catalog_button.setChecked(False); self.sidebar.hide(); self.scroll.show()

    def show_context(self):
        if self.context_provider is not None:
            key = self.context_provider()
            self.search.clear(); self.select_topic(key, force=True); self._finish_navigation()

    def _capture_reading(self):
        if self._history_index >= 0:
            self._history[self._history_index] = {
                'topic': self.topic_id, 'expanded': tuple(i for i, (button, _) in enumerate(self.sections) if button.isChecked()),
                'scroll': self.scroll.verticalScrollBar().value(),
                'demo': (self.diagram.width_slider.value(), self.diagram.level_slider.value())
                        if self.diagram is not None and hasattr(self.diagram, 'width_slider') else None,
            }

    def select_topic(self, key, section=None, force=False):
        if key not in TOPICS:
            return
        if key == self.topic_id and section is None and not force:
            return
        self._capture_reading()
        self._history = self._history[:self._history_index + 1]
        state = {'topic': key, 'expanded': () if section is None else (section,), 'scroll': 0}
        self._history.append(state); self._history_index += 1
        self._render(state, section)

    def go_back(self):
        self._travel(-1)

    def go_forward(self):
        self._travel(1)

    def _travel(self, step):
        target = self._history_index + step
        if 0 <= target < len(self._history):
            self._capture_reading(); self._history_index = target
            self._render(self._history[target]); self._finish_navigation()

    def _update_history_buttons(self):
        self.back_button.setEnabled(self._history_index > 0)
        self.forward_button.setEnabled(self._history_index + 1 < len(self._history))

    def _render(self, state, anchor=None):
        self._render_revision += 1; revision = self._render_revision
        self.topic_id = state['topic']; self.directory.setCurrentItem(self.topic_items[self.topic_id])
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget(); content.setObjectName('HelpContent')
        body = QVBoxLayout(content); body.setContentsMargins(18, 8, 14, 18); body.setSpacing(14)

        def label(text, name=None, target=body):
            widget = QLabel(text); widget.setWordWrap(True); widget.setTextFormat(Qt.PlainText)
            widget.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            if name:
                widget.setObjectName(name)
            target.addWidget(widget)
            return widget

        topic = TOPICS[self.topic_id]
        label(self.tr_text(topic['group']), 'HelpMeta')
        label(self.tr_text(topic['title']), 'HelpTitle')
        label(self.tr_text(topic['intro']))
        label(self.tr_text(('怎么用', 'How to use')), 'HelpMeta')
        label(self.tr_text(topic['steps']))
        self.sections = []; self.diagram = None
        for i, (title, text) in enumerate(topic['sections']):
            toggle = QToolButton(); toggle.setText(self.tr_text(title)); toggle.setCheckable(True)
            toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); toggle.setArrowType(Qt.RightArrow)
            toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); body.addWidget(toggle)
            detail = QWidget(); detail_layout = QVBoxLayout(detail); detail_layout.setContentsMargins(0, 0, 0, 4); detail_layout.setSpacing(12)
            if i == 0 and topic.get('diagram'):
                self.diagram = HelpDiagram(topic['diagram'], self.english); detail_layout.addWidget(self.diagram)
                if state.get('demo') is not None and hasattr(self.diagram, 'width_slider'):
                    self.diagram.width_slider.setValue(state['demo'][0]); self.diagram.level_slider.setValue(state['demo'][1])
            label(self.tr_text(text), target=detail_layout)
            detail.hide(); body.addWidget(detail)
            toggle.toggled.connect(detail.setVisible)
            toggle.toggled.connect(lambda on, toggle=toggle: toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow))
            toggle.setChecked(i in state['expanded']); self.sections.append((toggle, detail))
        label(self.tr_text(('相关主题', 'Related topics')), 'HelpMeta')
        self.related_buttons = {}
        for key in topic.get('related', ()):
            button = self._button(TOPICS[key]['title'], lambda checked=False, key=key: self.select_topic(key))
            self.related_buttons[key] = button; body.addWidget(button)
        body.addStretch(); self.scroll.setWidget(content); self._update_history_buttons()

        def position():
            # 主线程排版结束后定位；旧页面回调不能覆盖新页面阅读位置。
            if revision != self._render_revision:
                return
            content.layout().activate()
            if anchor is not None and 0 <= anchor < len(self.sections):
                self.scroll.verticalScrollBar().setValue(self.sections[anchor][0].y())
            else:
                self.scroll.verticalScrollBar().setValue(state['scroll'])

        QTimer.singleShot(0, self, position)

    def filter_topics(self, query):
        # 输入只更新检索结果；用户点击或按Enter才跳转到具体小节。
        active = bool(query.strip()); self.directory.setVisible(not active)
        self.results.clear()
        matches = search_topics(query, self.english) if active else []
        for match in matches:
            item = QListWidgetItem(f"{match['title']} › {match['heading']}\n{match['snippet']}")
            item.setData(Qt.UserRole, (match['topic'], match['section'])); self.results.addItem(item)
        self.results.setVisible(active and bool(matches)); self.no_results.setVisible(active and not matches)
        self.result_count.setVisible(active)
        self.result_count.setText(self.tr_text((f'{len(matches)} 处匹配 · 点击定位小节', f'{len(matches)} matches · select to open section')))
        if active:
            self.sidebar.show(); self.catalog_button.setChecked(True)
            if self._compact:
                self.scroll.hide()

    def _toggle_catalog(self):
        self.sidebar.setVisible(self.catalog_button.isChecked())
        self.scroll.setVisible(not self._compact or not self.catalog_button.isChecked())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 740
        if compact != self._compact and hasattr(self, 'sidebar'):
            self._compact = compact; self.catalog_button.setChecked(not compact)
            self.sidebar.setVisible(not compact); self.scroll.show()

    def done(self, result):
        super().done(result); self._restore_owner_focus()

    def closeEvent(self, event):
        super().closeEvent(event); self._restore_owner_focus()

    def _restore_owner_focus(self):
        owner = self.parentWidget()
        if owner is not None and owner.isVisible() and not getattr(owner, '_closing_help_owner', False):
            owner.activateWindow()
            target = owner.focusWidget()
            if target is not None and target.isVisible() and target.isEnabled():
                target.setFocus(Qt.OtherFocusReason)
            else:
                owner.setFocus(Qt.OtherFocusReason)
