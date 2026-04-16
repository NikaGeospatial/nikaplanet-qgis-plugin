from __future__ import annotations

import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
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

        name = worker.get("name", "Unknown Worker")
        version = worker.get("version", "?")
        self.setWindowTitle(f"{name} v{version}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setObjectName("npRunDialog")

        # Apply stylesheet before building child widgets so Qt
        # styles them as they are created.
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

        # machine type
        self._machine_combo = QComboBox()
        self._machine_combo.setObjectName("npRunCombo")
        for mt in ("CPUx3", "CPUx7", "CPUx20"):
            self._machine_combo.addItem(mt)
        form.addRow("Compute", self._machine_combo)

        # input fields
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

        # header: worker identification | session id
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

        # "Live Log" label
        log_lbl = QLabel("Live Log")
        log_lbl.setObjectName("npLogTabLabel")
        lay.addWidget(log_lbl)

        # log text area
        self._log_text = QPlainTextEdit()
        self._log_text.setObjectName("npLogArea")
        self._log_text.setReadOnly(True)
        lay.addWidget(self._log_text, 1)

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

    def _append_log(self, line: str):
        self._log_text.appendPlainText(line)

    def _on_status_change(self, status: str):
        self._status_lbl.setText(f"\u2022 {status}")
        if status in TERMINAL_STATUSES:
            self._cancel_btn.setEnabled(False)
            self._dur_timer.stop()

    def _tick_duration(self):
        if self._session:
            self._dur_lbl.setText(self._session.elapsed())

    def _on_cancel(self):
        if self._session:
            self._session.cancel()

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

        # string, number, datetime
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
        """Build a Qt file dialog filter string from a filetypes list.

        E.g. [".csv", ".geojson"] → "Supported files (*.csv *.geojson);;All files (*)"
        """
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
