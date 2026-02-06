#!/usr/bin/env python3
import os
import sys

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QToolBar, QStatusBar, QProgressBar,
    QDialog, QFormLayout, QComboBox, QCheckBox, QDialogButtonBox,
    QFileDialog, QMessageBox, QGroupBox, QHeaderView, QFrame,
)

import config
import venv_manager
import workers


class CreateVenvDialog(QDialog):
    def __init__(self, parent, default_location, task_manager):
        super().__init__(parent)
        self.setWindowTitle("Create New Virtual Environment")
        self.setMinimumWidth(480)
        self.task_manager = task_manager
        self.python_installs = []
        self.result_data = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("my-project")
        form.addRow("Name:", self.name_edit)

        loc_row = QHBoxLayout()
        self.loc_edit = QLineEdit(default_location)
        loc_row.addWidget(self.loc_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._browse_location)
        loc_row.addWidget(browse_btn)
        form.addRow("Location:", loc_row)

        self.python_combo = QComboBox()
        self.python_combo.addItem("Detecting...")
        self.python_combo.setEnabled(False)
        form.addRow("Python:", self.python_combo)

        self.pip_check = QCheckBox("Install pip")
        self.pip_check.setChecked(True)
        form.addRow("", self.pip_check)

        self.sys_check = QCheckBox("Include system site-packages")
        form.addRow("", self.sys_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.accepted.connect(self._on_create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._detect_pythons()

    def _browse_location(self):
        d = QFileDialog.getExistingDirectory(self, "Select Location", self.loc_edit.text())
        if d:
            self.loc_edit.setText(d)

    def _detect_pythons(self):
        self.task_manager.run(
            "detect_pythons",
            venv_manager.detect_python_versions, (),
            on_success=self._on_pythons_detected,
        )

    def _on_pythons_detected(self, installs):
        self.python_installs = installs
        self.python_combo.clear()
        self.python_combo.setEnabled(True)
        for p in installs:
            self.python_combo.addItem(p.display_name(), p.path)
        if not installs:
            self.python_combo.addItem("No Python found")
            self.python_combo.setEnabled(False)

    def _on_create(self):
        name = self.name_edit.text().strip()
        location = self.loc_edit.text().strip()
        idx = self.python_combo.currentIndex()

        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a name.")
            return
        if not self.python_installs or idx < 0:
            QMessageBox.warning(self, "No Python", "No Python version selected.")
            return

        full_path = os.path.join(location, name)
        if os.path.exists(full_path):
            QMessageBox.warning(self, "Exists", f"Directory already exists:\n{full_path}")
            return

        self.result_data = {
            "path": full_path,
            "python_path": self.python_installs[idx].path,
            "with_pip": self.pip_check.isChecked(),
            "system_site_packages": self.sys_check.isChecked(),
            "location": location,
        }
        self.accept()


class PyEnvyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyEnvy")
        self.setMinimumSize(800, 500)

        self.cfg = config.load_config()
        self.settings = QSettings("PyEnvy", "PyEnvy")
        self.task_manager = workers.TaskManager(status_callback=self._update_status)

        self.all_venvs = []
        self.selected_venv = None
        self.all_packages = []

        self._build_toolbar()
        self._build_central()
        self._build_status_bar()
        self._restore_geometry()
        self._refresh_venvs()

    # ── Toolbar ─────────────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        self.act_new = QAction("+ New Venv", self)
        self.act_new.triggered.connect(self._show_create_dialog)
        toolbar.addAction(self.act_new)

        self.act_delete = QAction("Delete", self)
        self.act_delete.triggered.connect(self._delete_selected_venv)
        self.act_delete.setEnabled(False)
        toolbar.addAction(self.act_delete)

        self.act_activate = QAction("Activate in Terminal", self)
        self.act_activate.triggered.connect(self._activate_selected_venv)
        self.act_activate.setEnabled(False)
        toolbar.addAction(self.act_activate)

        self.act_reveal = QAction("Reveal in Finder", self)
        self.act_reveal.triggered.connect(self._reveal_selected_venv)
        self.act_reveal.setEnabled(False)
        toolbar.addAction(self.act_reveal)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy(),
                             spacer.sizePolicy().verticalPolicy())
        from PyQt6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.act_refresh = QAction("Refresh", self)
        self.act_refresh.triggered.connect(self._refresh_venvs)
        toolbar.addAction(self.act_refresh)

    # ── Central Widget ──────────────────────────────────────────────

    def _build_central(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)

        header = QLabel("Virtual Environments")
        header.setFont(QFont("", 13, QFont.Weight.Bold))
        sidebar_layout.addWidget(header)

        self.venv_filter = QLineEdit()
        self.venv_filter.setPlaceholderText("Filter...")
        self.venv_filter.textChanged.connect(self._filter_venv_list)
        sidebar_layout.addWidget(self.venv_filter)

        self.venv_list = QListWidget()
        self.venv_list.currentRowChanged.connect(self._on_venv_selected)
        sidebar_layout.addWidget(self.venv_list)

        add_btn = QPushButton("+ Add Existing")
        add_btn.clicked.connect(self._browse_for_venv)
        sidebar_layout.addWidget(add_btn)

        splitter.addWidget(sidebar)

        # ── Main Panel ──
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Info group
        info_group = QGroupBox("Environment Details")
        info_layout = QFormLayout()
        info_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.info_labels = {}
        for key in ("Name", "Path", "Python", "Packages", "Status"):
            lbl = QLabel("—")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            info_layout.addRow(f"{key}:", lbl)
            self.info_labels[key] = lbl

        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)

        # Package group
        pkg_group = QGroupBox("Packages")
        pkg_layout = QVBoxLayout()

        # Package filter
        pkg_filter_row = QHBoxLayout()
        pkg_filter_row.addWidget(QLabel("Filter:"))
        self.pkg_filter = QLineEdit()
        self.pkg_filter.setPlaceholderText("Search packages...")
        self.pkg_filter.textChanged.connect(self._filter_package_list)
        pkg_filter_row.addWidget(self.pkg_filter)
        pkg_layout.addLayout(pkg_filter_row)

        # Package tree
        self.pkg_tree = QTreeWidget()
        self.pkg_tree.setHeaderLabels(["Package", "Version"])
        self.pkg_tree.setRootIsDecorated(False)
        self.pkg_tree.setAlternatingRowColors(True)
        self.pkg_tree.setSortingEnabled(True)
        self.pkg_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        header = self.pkg_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.pkg_tree.itemSelectionChanged.connect(self._on_package_selected)
        pkg_layout.addWidget(self.pkg_tree)

        # Package actions
        action_row = QHBoxLayout()
        self.pkg_entry = QLineEdit()
        self.pkg_entry.setPlaceholderText("package name (e.g. requests)")
        self.pkg_entry.returnPressed.connect(self._install_package)
        action_row.addWidget(self.pkg_entry)

        self.btn_install = QPushButton("Install")
        self.btn_install.clicked.connect(self._install_package)
        self.btn_install.setEnabled(False)
        action_row.addWidget(self.btn_install)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove_package)
        self.btn_remove.setEnabled(False)
        action_row.addWidget(self.btn_remove)

        self.btn_upgrade = QPushButton("Upgrade")
        self.btn_upgrade.clicked.connect(self._upgrade_package)
        self.btn_upgrade.setEnabled(False)
        action_row.addWidget(self.btn_upgrade)

        pkg_layout.addLayout(action_row)
        pkg_group.setLayout(pkg_layout)
        main_layout.addWidget(pkg_group)

        splitter.addWidget(main_panel)
        splitter.setSizes([250, 750])
        self.splitter = splitter

    # ── Status Bar ──────────────────────────────────────────────────

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.setMaximum(0)  # indeterminate
        self.progress.hide()
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.showMessage("Ready")

    def _update_status(self, message, busy=False):
        self.status_bar.showMessage(message)
        if busy:
            self.progress.show()
        else:
            self.progress.hide()

    # ── Geometry Persistence ────────────────────────────────────────

    def _restore_geometry(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1000, 650)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        config.save_config(self.cfg)
        event.accept()

    # ── Venv List ───────────────────────────────────────────────────

    def _refresh_venvs(self):
        def do_refresh():
            managed = venv_manager.load_managed_venvs(self.cfg.get("managed_venvs", []))
            discovered = venv_manager.discover_venvs(
                self.cfg.get("scan_directories", []),
                self.cfg.get("scan_max_depth", 3)
            )
            seen = set()
            merged = []
            for v in managed:
                real = os.path.realpath(v.path)
                if real not in seen:
                    merged.append(v)
                    seen.add(real)
            for v in discovered:
                real = os.path.realpath(v.path)
                if real not in seen:
                    merged.append(v)
                    seen.add(real)
            merged.sort(key=lambda v: v.name.lower())
            return merged

        self.task_manager.run(
            "refresh", do_refresh, (),
            on_success=self._on_venvs_loaded,
            on_error=lambda e: QMessageBox.critical(self, "Scan Error", str(e)),
            status_msg="Scanning for virtual environments..."
        )

    def _on_venvs_loaded(self, venvs):
        self.all_venvs = venvs
        self._populate_venv_list()

    def _populate_venv_list(self):
        self.venv_list.blockSignals(True)
        self.venv_list.clear()
        filter_text = self.venv_filter.text().lower()
        for v in self.all_venvs:
            if filter_text and filter_text not in v.name.lower():
                continue
            label = f"{v.name}  ({v.python_version})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, v.path)
            if not v.is_valid:
                item.setForeground(Qt.GlobalColor.gray)
            self.venv_list.addItem(item)
        self.venv_list.blockSignals(False)

    def _filter_venv_list(self):
        self._populate_venv_list()

    def _get_filtered_venvs(self):
        filter_text = self.venv_filter.text().lower()
        return [v for v in self.all_venvs
                if not filter_text or filter_text in v.name.lower()]

    # ── Venv Selection ──────────────────────────────────────────────

    def _on_venv_selected(self, row):
        if row < 0:
            self.selected_venv = None
            self._update_button_states()
            return
        filtered = self._get_filtered_venvs()
        if row >= len(filtered):
            return
        self.selected_venv = filtered[row]
        self._display_venv_details()
        self._load_packages()
        self._update_button_states()

    def _display_venv_details(self):
        v = self.selected_venv
        if not v:
            for lbl in self.info_labels.values():
                lbl.setText("—")
            return
        self.info_labels["Name"].setText(v.name)
        self.info_labels["Path"].setText(v.path)
        py_text = f"{v.python_version}  ({v.python_home})" if v.python_home else v.python_version
        self.info_labels["Python"].setText(py_text)
        self.info_labels["Status"].setText(
            f"Valid ({v.source})" if v.is_valid else f"Invalid ({v.source})")
        self.info_labels["Packages"].setText("Loading...")

    # ── Package Management ──────────────────────────────────────────

    def _load_packages(self):
        if not self.selected_venv:
            return
        venv_path = self.selected_venv.path
        self.task_manager.run(
            "list_packages",
            venv_manager.list_packages, (venv_path,),
            on_success=self._on_packages_loaded,
            on_error=lambda e: self._on_packages_error(e),
            status_msg="Loading packages..."
        )

    def _on_packages_loaded(self, packages):
        self.all_packages = packages
        self._populate_package_tree()
        self.info_labels["Packages"].setText(str(len(packages)))

    def _on_packages_error(self, error):
        self.all_packages = []
        self._populate_package_tree()
        self.info_labels["Packages"].setText("Error loading")

    def _populate_package_tree(self):
        self.pkg_tree.clear()
        filter_text = self.pkg_filter.text().lower()
        for pkg in self.all_packages:
            if filter_text and filter_text not in pkg.name.lower():
                continue
            item = QTreeWidgetItem([pkg.name, pkg.version])
            self.pkg_tree.addTopLevelItem(item)

    def _filter_package_list(self):
        self._populate_package_tree()

    def _on_package_selected(self):
        self._update_button_states()

    def _install_package(self):
        pkg_spec = self.pkg_entry.text().strip()
        if not pkg_spec or not self.selected_venv:
            return
        venv_path = self.selected_venv.path
        self.task_manager.run(
            "install_package",
            venv_manager.install_package, (venv_path, pkg_spec),
            on_success=lambda _: self._load_packages(),
            on_error=lambda e: QMessageBox.critical(self, "Install Error", str(e)),
            status_msg=f"Installing {pkg_spec}..."
        )
        self.pkg_entry.clear()

    def _remove_package(self):
        selected = self.pkg_tree.selectedItems()
        if not selected or not self.selected_venv:
            return
        names = [item.text(0) for item in selected]
        reply = QMessageBox.question(
            self, "Confirm Remove", f"Remove {', '.join(names)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        venv_path = self.selected_venv.path

        def do_remove():
            for name in names:
                venv_manager.remove_package(venv_path, name)
            return True

        self.task_manager.run(
            "remove_package", do_remove, (),
            on_success=lambda _: self._load_packages(),
            on_error=lambda e: QMessageBox.critical(self, "Remove Error", str(e)),
            status_msg=f"Removing {', '.join(names)}..."
        )

    def _upgrade_package(self):
        selected = self.pkg_tree.selectedItems()
        if not selected or not self.selected_venv:
            return
        names = [item.text(0) for item in selected]
        venv_path = self.selected_venv.path

        def do_upgrade():
            for name in names:
                venv_manager.upgrade_package(venv_path, name)
            return True

        self.task_manager.run(
            "upgrade_package", do_upgrade, (),
            on_success=lambda _: self._load_packages(),
            on_error=lambda e: QMessageBox.critical(self, "Upgrade Error", str(e)),
            status_msg=f"Upgrading {', '.join(names)}..."
        )

    # ── Create Venv ─────────────────────────────────────────────────

    def _show_create_dialog(self):
        default_loc = self.cfg.get("default_venv_location", os.path.expanduser("~/Envs"))
        dialog = CreateVenvDialog(self, default_loc, self.task_manager)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_data:
            data = dialog.result_data
            os.makedirs(data["location"], exist_ok=True)
            self.task_manager.run(
                "create_venv",
                venv_manager.create_venv,
                (data["path"], data["python_path"],
                 data["with_pip"], data["system_site_packages"]),
                on_success=self._on_venv_created,
                on_error=lambda e: QMessageBox.critical(self, "Create Error", str(e)),
                status_msg=f"Creating {os.path.basename(data['path'])}..."
            )

    def _on_venv_created(self, venv_info):
        self.cfg = config.add_managed_venv(self.cfg, venv_info.path)
        config.save_config(self.cfg)
        self._refresh_venvs()

    # ── Delete Venv ─────────────────────────────────────────────────

    def _delete_selected_venv(self):
        if not self.selected_venv:
            return
        v = self.selected_venv
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete virtual environment '{v.name}'?\n\nPath: {v.path}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        def do_delete():
            venv_manager.delete_venv(v.path)
            return v.path

        self.task_manager.run(
            "delete_venv", do_delete, (),
            on_success=self._on_venv_deleted,
            on_error=lambda e: QMessageBox.critical(self, "Delete Error", str(e)),
            status_msg=f"Deleting {v.name}..."
        )

    def _on_venv_deleted(self, path):
        self.cfg = config.remove_managed_venv(self.cfg, path)
        config.save_config(self.cfg)
        self.selected_venv = None
        self._display_venv_details()
        self.all_packages = []
        self._populate_package_tree()
        self._update_button_states()
        self._refresh_venvs()

    # ── Activate / Reveal ───────────────────────────────────────────

    def _activate_selected_venv(self):
        if not self.selected_venv:
            return
        self.task_manager.run(
            "activate",
            venv_manager.activate_in_terminal, (self.selected_venv.path,),
            on_success=lambda _: None,
            on_error=lambda e: QMessageBox.critical(self, "Activate Error", str(e)),
            status_msg="Opening Terminal..."
        )

    def _reveal_selected_venv(self):
        if not self.selected_venv:
            return
        try:
            venv_manager.reveal_in_finder(self.selected_venv.path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── Browse for Existing Venv ────────────────────────────────────

    def _browse_for_venv(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Virtual Environment Directory",
            os.path.expanduser("~"))
        if not directory:
            return
        cfg_path = os.path.join(directory, "pyvenv.cfg")
        if not os.path.exists(cfg_path):
            QMessageBox.warning(self, "Not a Venv",
                                "Selected directory does not appear to be a virtual environment.\n"
                                "(No pyvenv.cfg found)")
            return
        self.cfg = config.add_managed_venv(self.cfg, directory)
        config.save_config(self.cfg)
        self._refresh_venvs()

    # ── Button State Management ─────────────────────────────────────

    def _update_button_states(self):
        has_venv = self.selected_venv is not None
        has_valid = has_venv and self.selected_venv.is_valid
        has_pkg_sel = bool(self.pkg_tree.selectedItems())
        busy = self.task_manager.any_running()

        self.act_delete.setEnabled(has_venv and not busy)
        self.act_activate.setEnabled(has_valid)
        self.act_reveal.setEnabled(has_venv)
        self.btn_install.setEnabled(has_valid and not busy)
        self.btn_remove.setEnabled(has_valid and has_pkg_sel and not busy)
        self.btn_upgrade.setEnabled(has_valid and has_pkg_sel and not busy)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PyEnvy")
    app.setOrganizationName("PyEnvy")
    window = PyEnvyApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
