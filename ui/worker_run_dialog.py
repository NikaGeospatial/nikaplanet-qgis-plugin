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
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        title = QLabel(self._worker.get("name", "Unknown Worker"))
        title.setObjectName("npRunDialogTitle")
        lay.addWidget(title)

        ver = QLabel(f"Version: {self._worker.get('version', '?')}")
        ver.setObjectName("npRunDialogVersion")
        lay.addWidget(ver)

        desc = self._worker.get("description", "")
        if desc:
            d = QLabel(desc)
            d.setObjectName("npRunDialogDesc")
            d.setWordWrap(True)
            lay.addWidget(d)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(6)
        form.setContentsMargins(0, 4, 0, 4)

        self._machine_combo = QComboBox()
        self._machine_combo.setObjectName("npRunCombo")
        for mt in ("CPUx3", "CPUx7", "CPUx20"):
            self._machine_combo.addItem(mt)
        form.addRow("Compute", self._machine_combo)

        inputs_def = (
            self._worker.get("inputs")
            or self._worker.get("command", {}).get("inputs", [])
        )
        for inp in inputs_def:
            widget = self._build_input_widget(inp, form)
            self._input_widgets.append({"def": inp, "widget": widget})

        lay.addLayout(form)
        lay.addStretch()

        submit = QPushButton("Submit Run")
        submit.setObjectName("npSubmitRunBtn")
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.setFixedHeight(40)
        submit.clicked.connect(self._on_submit)
        lay.addWidget(submit)

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

        # Tabbed area: Log + Outputs
        self._detail_tabs = QTabWidget()
        self._detail_tabs.setObjectName("npDetailTabs")

        # -- Log tab --
        self._log_text = QPlainTextEdit()
        self._log_text.setObjectName("npLogArea")
        self._log_text.setReadOnly(True)
        self._detail_tabs.addTab(self._log_text, "Log")

        # -- Outputs tab --
        self._outputs_tree = QTreeWidget()
        self._outputs_tree.setObjectName("npOutputsTree")
        self._outputs_tree.setHeaderLabels(["Name", "Size"])
        self._outputs_tree.setRootIsDecorated(False)
        self._outputs_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._outputs_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._outputs_tree.customContextMenuRequested.connect(
            self._on_outputs_context_menu
        )
        self._outputs_tree.itemDoubleClicked.connect(self._on_output_double_click)
        self._detail_tabs.addTab(self._outputs_tree, "Outputs")
        self._detail_tabs.setTabEnabled(1, False)

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

        session.log_added.connect(self._append_log)
        session.status_changed.connect(self._on_status_change)

        self._dur_timer.start(1000)
        self._tick_duration()

        is_terminal = session.status in TERMINAL_STATUSES
        self._cancel_btn.setEnabled(not is_terminal)
        if is_terminal:
            self._dur_timer.stop()

        self._maybe_enable_outputs()

    def _append_log(self, line: str):
        self._log_text.appendPlainText(line)

    def _on_status_change(self, status: str):
        self._status_lbl.setText(f"\u2022 {status}")
        if status in TERMINAL_STATUSES:
            self._cancel_btn.setEnabled(False)
            self._dur_timer.stop()
        self._maybe_enable_outputs()

    def _tick_duration(self):
        if self._session:
            self._dur_lbl.setText(self._session.elapsed())

    def _on_cancel(self):
        if self._session:
            self._session.cancel()

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
            self._detail_tabs.setTabEnabled(1, True)
            self._load_outputs()

    def _load_outputs(self):
        """Fetch the output file listing in a background thread."""
        if not self._client or not self._session or not self._session.job_id:
            return
        self._outputs_loaded = True
        job_id = self._session.job_id
        threading.Thread(
            target=self._fetch_outputs, args=(job_id,), daemon=True,
        ).start()

    def _fetch_outputs(self, job_id: str):
        try:
            files, sub_dirs = self._client.list_outputs(job_id)
            from functools import partial
            QTimer.singleShot(0, partial(self._populate_outputs, files, sub_dirs))
        except Exception as exc:
            QTimer.singleShot(
                0,
                lambda: self._append_log(f"[ERROR] Failed to load outputs: {exc}"),
            )

    def _populate_outputs(self, files, sub_dirs):
        self._outputs_tree.clear()

        for entry in sub_dirs:
            name = entry.path.rstrip("/").rsplit("/", 1)[-1] + "/"
            item = QTreeWidgetItem([name, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "path": entry.path, "isDir": True,
            })
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._outputs_tree.addTopLevelItem(item)

        for entry in files:
            fname = entry.path.rsplit("/", 1)[-1]
            item = QTreeWidgetItem([fname, entry.size or ""])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "path": entry.path, "isDir": False, "name": fname,
            })
            self._outputs_tree.addTopLevelItem(item)

        self._outputs_tree.resizeColumnToContents(0)

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
        # Strip /outputs prefix to get the path for the download endpoint.
        rel_path = output_path.replace("/outputs", "", 1)

        def _do_download():
            try:
                from ..cloud.client import download_file
                signed_url = self._client.get_output_download_url(job_id, rel_path)
                download_file(signed_url, local_path)
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Downloaded: {filename} -> {local_path}"
                ))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._append_log(
                    f"Download failed: {exc}"
                ))

        threading.Thread(target=_do_download, daemon=True).start()

    def _on_output_double_click(self, item: QTreeWidgetItem, _column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and not data.get("isDir"):
            self._download_output(data["path"], data["name"])

    def _on_outputs_context_menu(self, pos):
        selected = [
            item for item in self._outputs_tree.selectedItems()
            if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("isDir") is False
        ]
        all_files = [
            self._outputs_tree.topLevelItem(i)
            for i in range(self._outputs_tree.topLevelItemCount())
            if (self._outputs_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or {}).get("isDir") is False
        ]

        menu = QMenu(self)

        dl_action = None
        if len(selected) == 1:
            dl_action = menu.addAction("Download")
        elif len(selected) > 1:
            dl_action = menu.addAction(f"Download {len(selected)} files")

        dl_all_action = None
        if all_files and set(id(i) for i in all_files) != set(id(i) for i in selected):
            dl_all_action = menu.addAction(f"Download all ({len(all_files)} files)")

        if not menu.actions():
            return

        action = menu.exec(self._outputs_tree.viewport().mapToGlobal(pos))
        if action == dl_action and selected:
            self._download_items(selected)
        elif action == dl_all_action and all_files:
            self._download_items(all_files)

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
            rel_path = data["path"].replace("/outputs", "", 1)
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

    # ── submit ────────────────────────────────────────────────────

    def _on_submit(self):
        schema_with_args = []
        for item in self._input_widgets:
            inp_def = item["def"]
            widget = item["widget"]
            inp_type = inp_def.get("type", "string")
            readonly = inp_def.get("readonly", False)
            value = self._widget_value(widget)

            entry: dict = {
                "name": inp_def.get("name", ""),
                "type": inp_type,
            }
            for key in ("readonly", "required", "description", "enum_values", "default", "filetypes"):
                if key in inp_def:
                    entry[key] = inp_def[key]

            if inp_type == "folder" and not readonly:
                pass
            elif value:
                entry["args"] = value

            if readonly and value and inp_type in ("file", "folder"):
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

    def _build_input_widget(self, inp: dict, form: QFormLayout):
        inp_type = inp.get("type", "string")
        inp_desc = inp.get("description", inp.get("name", ""))
        required = inp.get("required", False)
        readonly = inp.get("readonly", False)

        label_text = inp_desc or inp.get("name", "")
        if required:
            label_text += " *"

        if inp_type == "file":
            filetypes = inp.get("filetypes")
            return self._build_file_row(label_text, readonly, form, filetypes=filetypes)
        if inp_type == "folder":
            return self._build_folder_row(label_text, readonly, form)
        if inp_type == "boolean":
            cb = QCheckBox()
            cb.setObjectName("npRunCheckbox")
            form.addRow(label_text, cb)
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
            form.addRow(label_text, combo)
            return combo

        le = QLineEdit()
        le.setObjectName("npRunInput")
        default = inp.get("default")
        if default is not None:
            le.setText(str(default))
        else:
            le.setPlaceholderText(f"Enter {inp_type}\u2026")
        form.addRow(label_text, le)
        return le

    def _build_file_row(self, label_text, readonly, form, filetypes=None):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit()
        le.setObjectName("npRunInput")
        le.setPlaceholderText(
            "Select input file\u2026" if readonly else "Select output file location\u2026"
        )
        row.addWidget(le, 1)
        browse = QPushButton("Browse")
        browse.setObjectName("npBrowseBtn")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        file_filter = self._build_file_filter(filetypes)
        if readonly:
            browse.clicked.connect(
                lambda _=False, w=le, ff=file_filter: self._pick_open_file(w, ff)
            )
        else:
            browse.clicked.connect(
                lambda _=False, w=le, ff=file_filter: self._pick_save_file(w, ff)
            )
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        form.addRow(label_text, container)
        return le

    def _build_folder_row(self, label_text, readonly, form):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit()
        le.setObjectName("npRunInput")
        if readonly:
            le.setPlaceholderText("Select input folder\u2026")
        else:
            le.setPlaceholderText("Output folder (server sets path)")
            le.setReadOnly(True)
        row.addWidget(le, 1)
        if readonly:
            browse = QPushButton("Browse")
            browse.setObjectName("npBrowseBtn")
            browse.setCursor(Qt.CursorShape.PointingHandCursor)
            browse.clicked.connect(lambda _=False, w=le: self._pick_folder(w))
            row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        form.addRow(label_text, container)
        return le

    # ── pickers ───────────────────────────────────────────────────

    def _pick_open_file(self, le: QLineEdit, file_filter: str = ""):
        path, _ = QFileDialog.getOpenFileName(self, "Select Input File", "", file_filter)
        if path:
            le.setText(path)

    def _pick_save_file(self, le: QLineEdit, file_filter: str = ""):
        path, _ = QFileDialog.getSaveFileName(self, "Select Output File Location", "", file_filter)
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
