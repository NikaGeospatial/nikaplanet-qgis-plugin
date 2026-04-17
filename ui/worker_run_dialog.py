from __future__ import annotations

import os
import threading

from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal

from .job_session import TERMINAL_STATUSES, JobSession


class WorkerRunDialog(QDialog):
    """Dialog for configuring a worker run and viewing live logs."""

    job_submitted = pyqtSignal(object)  # emits JobSession

    def __init__(
        self,
        worker: dict,
        session: JobSession | None = None,
        stylesheet: str = "",
        client=None,
        parent=None,
    ):
        super().__init__(parent)
        self._worker = worker
        self._client = client
        self._session = None
        self._input_widgets: list[dict] = []
        self._outputs_loaded = False

        name = worker.get("name", "Unknown Worker")
        version = worker.get("version", "?")
        self.setWindowTitle(f"{name} v{version}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setObjectName("npRunDialog")

        if not stylesheet:
            from .styles import DARK_STYLESHEET
            stylesheet = DARK_STYLESHEET
        self.setStyleSheet(stylesheet)

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        main_lay.addWidget(self._stack)

        self._stack.addWidget(self._build_config_page())    # index 0
        self._stack.addWidget(self._build_log_page())       # index 1

        if session:
            self._attach_session(session)

    # ── config page ───────────────────────────────────────────────

    def _build_config_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Scrollable area for all config content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(20, 20, 20, 20)
        inner_lay.setSpacing(12)

        title = QLabel(self._worker.get("name", "Unknown Worker"))
        title.setObjectName("npRunDialogTitle")
        inner_lay.addWidget(title)

        ver = QLabel(f"Version: {self._worker.get('version', '?')}")
        ver.setObjectName("npRunDialogVersion")
        inner_lay.addWidget(ver)

        desc = self._worker.get("description", "")
        if desc:
            d = QLabel(desc)
            d.setObjectName("npRunDialogDesc")
            d.setWordWrap(True)
            inner_lay.addWidget(d)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(6)
        form.setContentsMargins(0, 4, 0, 4)

        self._machine_combo = QComboBox()
        self._machine_combo.setObjectName("npRunCombo")
        plan = self._worker.get("planFeatures") or {}
        cpu_types = plan.get("cpu_machine_types") or []
        gpu_types = plan.get("gpu_machine_types") or []
        all_types = cpu_types + gpu_types
        if not all_types:
            all_types = ["CPUx3"]
        for mt in all_types:
            self._machine_combo.addItem(mt)
        form.addRow(self._make_form_label("Compute"), self._machine_combo)

        inputs_def = (
            self._worker.get("inputs")
            or self._worker.get("command", {}).get("inputs", [])
        )
        for inp in inputs_def:
            widget = self._build_input_widget(inp, form)
            self._input_widgets.append({"def": inp, "widget": widget})

        inner_lay.addLayout(form)
        inner_lay.addStretch()

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        # Submit button stays pinned at the bottom, outside the scroll
        submit = QPushButton("Submit Run")
        submit.setObjectName("npSubmitRunBtn")
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.setFixedHeight(40)
        submit.clicked.connect(self._on_submit)
        btn_wrap = QWidget()
        btn_lay = QVBoxLayout(btn_wrap)
        btn_lay.setContentsMargins(20, 8, 20, 20)
        btn_lay.addWidget(submit)
        lay.addWidget(btn_wrap)

        return page

    # ── log page ──────────────────────────────────────────────────

    def _build_log_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        # header
        header = QHBoxLayout()

        left = QVBoxLayout()
        left.setSpacing(2)
        wid_lbl = QLabel("WORKER IDENTIFICATION")
        wid_lbl.setObjectName("npLogSectionLabel")
        left.addWidget(wid_lbl)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        n = QLabel(self._worker.get("name", "unknown"))
        n.setObjectName("npRunDialogTitle")
        name_row.addWidget(n)
        badge = QLabel(f" v{self._worker.get('version', '?')} ")
        badge.setObjectName("npVersionBadge")
        name_row.addWidget(badge)
        name_row.addStretch()
        left.addLayout(name_row)

        header.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        sid_title = QLabel("SESSION ID")
        sid_title.setObjectName("npLogSectionLabel")
        sid_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(sid_title)
        self._sid_lbl = QLabel("")
        self._sid_lbl.setObjectName("npSessionId")
        self._sid_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._sid_lbl)

        header.addLayout(right)
        lay.addLayout(header)

        # status / duration cards
        cards = QHBoxLayout()
        cards.setSpacing(12)

        status_card = QWidget()
        status_card.setObjectName("npStatusCard")
        sc = QHBoxLayout(status_card)
        sc.setContentsMargins(12, 8, 12, 8)
        sc.setSpacing(6)
        sc_t = QLabel("CURRENT STATUS")
        sc_t.setObjectName("npLogSectionLabel")
        sc.addWidget(sc_t)
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("npStatusValue")
        sc.addWidget(self._status_lbl)
        sc.addStretch()
        cards.addWidget(status_card, 1)

        dur_card = QWidget()
        dur_card.setObjectName("npStatusCard")
        dc = QHBoxLayout(dur_card)
        dc.setContentsMargins(12, 8, 12, 8)
        dc.setSpacing(6)
        dc_t = QLabel("DURATION")
        dc_t.setObjectName("npLogSectionLabel")
        dc.addWidget(dc_t)
        self._dur_lbl = QLabel("0m 0s")
        self._dur_lbl.setObjectName("npDurationValue")
        dc.addWidget(self._dur_lbl)
        dc.addStretch()
        cards.addWidget(dur_card, 1)

        lay.addLayout(cards)

        # Tabbed area: Log + Inputs + Outputs
        self._detail_tabs = QTabWidget()
        self._detail_tabs.setObjectName("npDetailTabs")

        # -- Log tab (index 0) --
        self._log_text = QPlainTextEdit()
        self._log_text.setObjectName("npLogArea")
        self._log_text.setReadOnly(True)
        self._detail_tabs.addTab(self._log_text, "Log")

        # -- Inputs tab (index 1) --
        inputs_scroll = QScrollArea()
        inputs_scroll.setWidgetResizable(True)
        inputs_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._inputs_form_widget = QWidget()
        self._inputs_form = QFormLayout(self._inputs_form_widget)
        self._inputs_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self._inputs_form.setSpacing(6)
        self._inputs_form.setContentsMargins(12, 12, 12, 12)
        inputs_scroll.setWidget(self._inputs_form_widget)
        self._detail_tabs.addTab(inputs_scroll, "Inputs")

        # -- Outputs tab (index 2) --
        self._outputs_tree = QTreeWidget()
        self._outputs_tree.setObjectName("npOutputsTree")
        self._outputs_tree.setHeaderLabels(["Name", "Size"])
        self._outputs_tree.setRootIsDecorated(True)
        self._outputs_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._outputs_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._outputs_tree.customContextMenuRequested.connect(
            self._on_outputs_context_menu
        )
        self._outputs_tree.itemExpanded.connect(self._on_folder_expanded)
        self._outputs_tree.itemDoubleClicked.connect(self._on_output_double_click)

        self._detail_tabs.addTab(self._outputs_tree, "Outputs")
        self._detail_tabs.setTabEnabled(2, False)

        lay.addWidget(self._detail_tabs, 1)

        # cancel button
        self._cancel_btn = QPushButton("CANCEL SESSION")
        self._cancel_btn.setObjectName("npCancelBtn")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.clicked.connect(self._on_cancel)
        lay.addWidget(self._cancel_btn)

        # duration ticker
        self._dur_timer = QTimer(self)
        self._dur_timer.timeout.connect(self._tick_duration)

        return page

    # ── session binding ───────────────────────────────────────────

    def _attach_session(self, session: JobSession):
        self._session = session
        self._stack.setCurrentIndex(1)
        self._sid_lbl.setText(session.session_id)
        self._status_lbl.setText(f"\u2022 {session.status}")

        self._log_text.clear()
        for line in session.logs:
            self._log_text.appendPlainText(line)

        self._populate_inputs(session.input_args)

        session.log_added.connect(self._append_log)
        session.status_changed.connect(self._on_status_change)
        session.session_id_changed.connect(self._sid_lbl.setText)

        self._dur_timer.start(1000)
        self._tick_duration()

        is_terminal = session.status in TERMINAL_STATUSES
        self._cancel_btn.setVisible(not is_terminal)
        if is_terminal:
            self._dur_timer.stop()

        self._maybe_enable_outputs()

    def _append_log(self, line: str):
        self._log_text.appendPlainText(line)

    def _on_status_change(self, status: str):
        self._status_lbl.setText(f"\u2022 {status}")
        if status in TERMINAL_STATUSES:
            self._cancel_btn.hide()
            self._dur_timer.stop()
        self._maybe_enable_outputs()

    def _tick_duration(self):
        if self._session:
            self._dur_lbl.setText(self._session.elapsed())

    def _on_cancel(self):
        if self._session:
            self._session.cancel()

    # ── inputs tab ───────────────────────────────────────────────

    def _populate_inputs(self, input_args: list[dict]):
        """Fill the Inputs tab with read-only name/value rows."""
        # Clear any previous rows.
        while self._inputs_form.rowCount():
            self._inputs_form.removeRow(0)

        if not input_args:
            empty = QLabel("No inputs.")
            empty.setObjectName("npLogSectionLabel")
            self._inputs_form.addRow(empty)
            return

        for entry in input_args:
            label_text = entry.get("description") or entry.get("name", "")
            inp_type = entry.get("type", "string")
            is_output = entry.get("output", False)
            value = entry.get("args", "")

            if is_output:
                label_text = f"{label_text}  (output)"

            val_lbl = QLabel(str(value) if value else "\u2014")
            val_lbl.setObjectName("npRunInput")
            val_lbl.setWordWrap(True)
            val_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._inputs_form.addRow(self._make_form_label(label_text), val_lbl)

    # ── outputs tab ──────────────────────────────────────────────

    def _maybe_enable_outputs(self):
        """Enable and populate the Outputs tab when applicable."""
        if not self._session:
            return
        if (
            self._session.status == "SUCCESS"
            and self._session.has_output_files
            and not self._outputs_loaded
        ):
            self._detail_tabs.setTabEnabled(2, True)
            self._load_outputs()

    def _load_outputs(self):
        """Fetch the root output listing in a background thread."""
        if not self._client or not self._session or not self._session.job_id:
            return
        self._outputs_loaded = True
        self._fetch_outputs_for_path("/")

    def _fetch_outputs_for_path(
        self, path: str, parent_item: QTreeWidgetItem | None = None,
    ):
        if not self._client or not self._session or not self._session.job_id:
            return
        job_id = self._session.job_id
        threading.Thread(
            target=self._fetch_outputs,
            args=(job_id, path, parent_item),
            daemon=True,
        ).start()

    def _fetch_outputs(
        self, job_id: str, path: str, parent_item: QTreeWidgetItem | None,
    ):
        try:
            files, sub_dirs = self._client.list_outputs(job_id, path)
            from functools import partial
            QTimer.singleShot(
                0, partial(self._populate_outputs, files, sub_dirs, parent_item),
            )
        except Exception as exc:
            QTimer.singleShot(
                0,
                lambda: self._append_log(f"[ERROR] Failed to load outputs: {exc}"),
            )

    @staticmethod
    def _strip_outputs_prefix(path: str) -> str:
        """Remove the /outputs prefix the API includes in returned paths."""
        if path.startswith("/outputs"):
            return path[len("/outputs"):] or "/"
        return path

    def _make_folder_item(self, path: str) -> QTreeWidgetItem:
        name = path.rstrip("/").rsplit("/", 1)[-1]
        item = QTreeWidgetItem([name, ""])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "path": path, "isDir": True, "loaded": False,
        })
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
        )
        # Dummy child so expand triggers a fetch.
        item.addChild(QTreeWidgetItem(["\u2026", ""]))
        return item

    @staticmethod
    def _make_file_item(path: str, fname: str, size: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([fname, size])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "path": path, "isDir": False, "name": fname,
        })
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless
        )
        return item

    def _populate_outputs(self, files, sub_dirs, parent_item=None):
        if parent_item is None:
            self._outputs_tree.clear()
        else:
            parent_item.takeChildren()

        target = parent_item or self._outputs_tree.invisibleRootItem()

        for entry in sub_dirs:
            clean = self._strip_outputs_prefix(entry.path)
            target.addChild(self._make_folder_item(clean))

        for entry in files:
            clean = self._strip_outputs_prefix(entry.path)
            fname = clean.rsplit("/", 1)[-1]
            target.addChild(self._make_file_item(clean, fname, entry.size or ""))

        self._outputs_tree.resizeColumnToContents(0)

    def _on_folder_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.get("isDir") or data.get("loaded"):
            return
        data["loaded"] = True
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        self._fetch_outputs_for_path(data["path"], parent_item=item)

    def _on_output_double_click(self, item: QTreeWidgetItem, _column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and not data.get("isDir"):
            self._download_output(data["path"], data["name"])

    def _download_output(self, output_path: str, filename: str):
        """Prompt the user for a save location, then download the file."""
        local_path, _ = QFileDialog.getSaveFileName(
            self, "Save Output File", filename,
        )
        if not local_path:
            return
        if not self._client or not self._session or not self._session.job_id:
            return

        job_id = self._session.job_id

        def _do_download():
            try:
                from ..cloud.client import download_file
                signed_url = self._client.get_output_download_url(job_id, output_path)
                download_file(signed_url, local_path)
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Downloaded: {filename} -> {local_path}"
                ))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Download failed: {exc}"
                ))

        threading.Thread(target=_do_download, daemon=True).start()

    _SHP_EXTENSIONS = frozenset({".shp", ".shx", ".dbf", ".prj", ".cpg"})

    def _find_shapefile_siblings(self, item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        """Return all sibling items that share the same stem and have a shapefile extension."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("isDir"):
            return []
        name = data.get("name", "")
        stem, ext = os.path.splitext(name)
        if ext.lower() not in self._SHP_EXTENSIONS:
            return []

        parent = item.parent() or self._outputs_tree.invisibleRootItem()
        siblings = []
        for i in range(parent.childCount()):
            child = parent.child(i)
            cd = child.data(0, Qt.ItemDataRole.UserRole)
            if not cd or cd.get("isDir"):
                continue
            child_stem, child_ext = os.path.splitext(cd.get("name", ""))
            if child_stem == stem and child_ext.lower() in self._SHP_EXTENSIONS:
                siblings.append(child)
        return siblings

    def _on_outputs_context_menu(self, pos):
        all_selected = self._outputs_tree.selectedItems()
        file_items = [
            item for item in all_selected
            if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("isDir") is False
        ]
        folder_items = [
            item for item in all_selected
            if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("isDir") is True
        ]

        menu = QMenu(self)
        menu.setObjectName("npOutputsMenu")

        # Single file download
        dl_action = None
        if len(file_items) == 1:
            dl_action = menu.addAction("Download")
        elif len(file_items) > 1:
            dl_action = menu.addAction(f"Download {len(file_items)} files")

        # Shapefile: download all associated files
        dl_shp_action = None
        shp_siblings: list[QTreeWidgetItem] = []
        if len(file_items) == 1:
            shp_siblings = self._find_shapefile_siblings(file_items[0])
            if len(shp_siblings) > 1:
                stem = os.path.splitext(
                    file_items[0].data(0, Qt.ItemDataRole.UserRole)["name"]
                )[0]
                exts = ", ".join(
                    sorted(os.path.splitext(
                        s.data(0, Qt.ItemDataRole.UserRole)["name"]
                    )[1] for s in shp_siblings)
                )
                dl_shp_action = menu.addAction(
                    f"Download shapefile \"{stem}\" ({exts})"
                )

        # Folder download (as zip)
        dl_folder_action = None
        if len(folder_items) == 1:
            name = folder_items[0].text(0)
            dl_folder_action = menu.addAction(f"Download folder \"{name}\" as zip")
        elif len(folder_items) > 1:
            dl_folder_action = menu.addAction(
                f"Download {len(folder_items)} folders as zip"
            )

        # Download all outputs as zip
        dl_all_action = menu.addAction("Download all outputs as zip")

        if not menu.actions():
            return

        action = menu.exec(self._outputs_tree.viewport().mapToGlobal(pos))
        if action == dl_action and file_items:
            self._download_items(file_items)
        elif action == dl_shp_action and shp_siblings:
            self._download_items(shp_siblings)
        elif action == dl_folder_action and folder_items:
            self._download_folders(folder_items)
        elif action == dl_all_action:
            self._download_folder_path("/")

    def _download_items(self, items: list[QTreeWidgetItem]):
        if len(items) == 1:
            data = items[0].data(0, Qt.ItemDataRole.UserRole)
            self._download_output(data["path"], data["name"])
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Save Output Files To")
        if not dest_dir:
            return
        if not self._client or not self._session or not self._session.job_id:
            return

        job_id = self._session.job_id
        entries = []
        for item in items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            rel_path = data["path"]
            local_path = os.path.join(dest_dir, data["name"])
            entries.append((rel_path, local_path, data["name"]))

        def _do_batch():
            from ..cloud.client import download_file
            for rel_path, local_path, name in entries:
                try:
                    signed_url = self._client.get_output_download_url(job_id, rel_path)
                    download_file(signed_url, local_path)
                    QTimer.singleShot(0, lambda n=name, lp=local_path: self._append_log(
                        f"Downloaded: {n} -> {lp}"
                    ))
                except Exception as exc:
                    QTimer.singleShot(0, lambda n=name, e=exc: self._append_log(
                        f"Download failed ({n}): {e}"
                    ))

        threading.Thread(target=_do_batch, daemon=True).start()

    def _download_folders(self, items: list[QTreeWidgetItem]):
        for item in items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            self._download_folder_path(data["path"])

    def _download_folder_path(self, path: str):
        if path == "/":
            default_name = "outputs.zip"
        else:
            default_name = path.rstrip("/").rsplit("/", 1)[-1] + ".zip"

        local_path, _ = QFileDialog.getSaveFileName(
            self, "Save Folder as Zip", default_name, "Zip files (*.zip)",
        )
        if not local_path:
            return
        if not self._client or not self._session or not self._session.job_id:
            return

        job_id = self._session.job_id

        def _do_download():
            try:
                self._client.download_output_folder(job_id, path, local_path)
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Downloaded folder: {default_name} -> {local_path}"
                ))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Folder download failed: {exc}"
                ))

        threading.Thread(target=_do_download, daemon=True).start()

    # ── submit ────────────────────────────────────────────────────

    def _on_submit(self):
        schema_with_args = []
        for item in self._input_widgets:
            inp_def = item["def"]
            widget = item["widget"]
            inp_type = inp_def.get("type", "string")
            is_output = inp_def.get("output", False)
            value = self._widget_value(widget)

            entry: dict = {
                "name": inp_def.get("name", ""),
                "type": inp_type,
            }
            for key in ("output", "required", "description", "enum_values", "default", "filetypes"):
                if key in inp_def:
                    entry[key] = inp_def[key]

            if is_output and value and inp_type == "folder":
                entry["args"] = value if value.endswith("/") else value + "/"
            elif value:
                entry["args"] = value

            if not is_output and value and inp_type in ("file", "folder"):
                tree = self._build_directory_tree(value, inp_type)
                if tree:
                    entry["directoryTree"] = tree

            schema_with_args.append(entry)

        session = JobSession(
            worker_name=self._worker.get("name", "unknown"),
            version=self._worker.get("version", "?"),
            tenant_id=self._worker.get("tenantId", ""),
            machine_type=self._machine_combo.currentText(),
            input_args=schema_with_args,
            worker_id=self._worker.get("id", ""),
            client=self._client,
        )
        self.job_submitted.emit(session)
        self._attach_session(session)

    # ── input widget builders ─────────────────────────────────────

    @staticmethod
    def _make_form_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("npRunFormLabel")
        lbl.setWordWrap(True)
        lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.MinimumExpanding,
        )
        lbl.setMinimumWidth(1)
        return lbl

    def _build_input_widget(self, inp: dict, form: QFormLayout):
        inp_type = inp.get("type", "string")
        inp_desc = inp.get("description", inp.get("name", ""))
        required = inp.get("required", False)
        is_output = inp.get("output", False)

        label_text = inp_desc or inp.get("name", "")
        if required:
            label_text += " *"

        if inp_type == "file":
            filetypes = inp.get("filetypes")
            return self._build_file_row(label_text, is_output, form, filetypes=filetypes)
        if inp_type == "folder":
            return self._build_folder_row(label_text, is_output, form)
        if inp_type == "boolean":
            cb = QCheckBox()
            cb.setObjectName("npRunCheckbox")
            form.addRow(self._make_form_label(label_text), cb)
            return cb
        if inp_type == "enum":
            combo = QComboBox()
            combo.setObjectName("npRunCombo")
            for val in inp.get("enum_values", []):
                combo.addItem(val)
            default = inp.get("default")
            if default:
                idx = combo.findText(str(default))
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            form.addRow(self._make_form_label(label_text), combo)
            return combo

        le = QLineEdit()
        le.setObjectName("npRunInput")
        default = inp.get("default")
        if default is not None:
            le.setText(str(default))
        else:
            le.setPlaceholderText(f"Enter {inp_type}\u2026")
        form.addRow(self._make_form_label(label_text), le)
        return le

    def _build_file_row(self, label_text, is_output, form, filetypes=None):
        if is_output:
            le = QLineEdit()
            le.setObjectName("npRunInput")
            le.setPlaceholderText("Enter output file name\u2026")
            form.addRow(self._make_form_label(label_text), le)
            return le
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit()
        le.setObjectName("npRunInput")
        le.setPlaceholderText("Select input file\u2026")
        row.addWidget(le, 1)
        browse = QPushButton("Browse")
        browse.setObjectName("npBrowseBtn")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        file_filter = self._build_file_filter(filetypes)
        browse.clicked.connect(
            lambda _=False, w=le, ff=file_filter: self._pick_open_file(w, ff)
        )
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        form.addRow(self._make_form_label(label_text), container)
        return le

    def _build_folder_row(self, label_text, is_output, form):
        if is_output:
            le = QLineEdit()
            le.setObjectName("npRunInput")
            le.setPlaceholderText("Enter output folder name\u2026")
            form.addRow(self._make_form_label(label_text), le)
            return le
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit()
        le.setObjectName("npRunInput")
        le.setPlaceholderText("Select input folder\u2026")
        row.addWidget(le, 1)
        browse = QPushButton("Browse")
        browse.setObjectName("npBrowseBtn")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(lambda _=False, w=le: self._pick_folder(w))
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        form.addRow(self._make_form_label(label_text), container)
        return le

    # ── pickers ───────────────────────────────────────────────────

    def _pick_open_file(self, le: QLineEdit, file_filter: str = ""):
        path, _ = QFileDialog.getOpenFileName(self, "Select Input File", "", file_filter)
        if path:
            le.setText(path)

    def _pick_folder(self, le: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            le.setText(path)

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _widget_value(widget) -> str | None:
        if isinstance(widget, QCheckBox):
            return str(widget.isChecked()).lower()
        if isinstance(widget, QComboBox):
            return widget.currentText() or None
        if isinstance(widget, QLineEdit):
            return widget.text().strip() or None
        return None

    @staticmethod
    def _build_file_filter(filetypes: list[str] | None) -> str:
        if not filetypes:
            return ""
        exts = " ".join(f"*{ft}" for ft in filetypes)
        return f"Supported files ({exts});;All files (*)"

    @staticmethod
    def _build_directory_tree(local_path: str, inp_type: str) -> list[dict] | None:
        if inp_type == "file" and os.path.isfile(local_path):
            return [{
                "path": os.path.basename(local_path),
                "sizeInBytes": os.path.getsize(local_path),
            }]
        if inp_type == "folder" and os.path.isdir(local_path):
            parent = os.path.dirname(local_path.rstrip(os.sep))
            tree = []
            for root, _dirs, files in os.walk(local_path):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, parent)
                    tree.append({
                        "path": rel,
                        "sizeInBytes": os.path.getsize(full),
                    })
            return tree if tree else None
        return None
