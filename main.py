import sys, sqlite3, json, shutil, uuid
from pathlib import Path
from datetime import date
from PySide6.QtCore import Qt, QUrl, QStandardPaths
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import *
ROOT=Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)); ROOT.mkdir(parents=True,exist_ok=True)
MEDIA=ROOT/'media'; MEDIA.mkdir(exist_ok=True)
DB=sqlite3.connect(ROOT/'voyager.sqlite'); DB.row_factory=sqlite3.Row
DB.executescript('CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, day TEXT, title TEXT, notes TEXT, reflection TEXT, composition TEXT, curriculum TEXT, mission TEXT); CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY, entry_id INTEGER, name TEXT, path TEXT);')
FIELDS=['day','title','notes','reflection','composition','curriculum','mission']
def attach(eid,path):
    p=Path(path); target=MEDIA/(uuid.uuid4().hex+p.suffix); shutil.copy2(p,target); DB.execute('INSERT INTO media(entry_id,name,path) VALUES(?,?,?)',(eid,p.name,target.name)); DB.commit()
if not DB.execute('SELECT 1 FROM entries LIMIT 1').fetchone():
    eid=DB.execute('INSERT INTO entries(day,title,notes,reflection,composition,curriculum,mission) VALUES(?,?,?,?,?,?,?)',('2026-11-25','Two chords, one shape','A minor: x02210; E major: 022100.','Learner reports being comfortable with the chords.','Leaving Earth — suggested 8 bars at 60 BPM: Am Am E E Am E E Am.','Teach shared fingering shape, clean strings and four-beat transitions.','Earth and Moon')).lastrowid; DB.commit()
    for p in (Path(__file__).parent/'seed').glob('*'): attach(eid,p)
class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Project Voyager | Guitar learning journal'); self.resize(1200,800); self.eid=None; self.dirty=False; self.loading=False
        base=QWidget(); self.setCentralWidget(base); layout=QHBoxLayout(base)
        side=QVBoxLayout(); layout.addLayout(side,1); side.addWidget(QLabel('PROJECT VOYAGER')); self.list=QListWidget(); side.addWidget(self.list); self.list.currentItemChanged.connect(self.select)
        for label,fn in [('New diary entry',self.new),('Save entry',self.save),('Export AI brief',self.export),('Import AI response',self.import_ai)]:
            b=QPushButton(label); b.clicked.connect(fn); side.addWidget(b)
        side.addWidget(QLabel(str(ROOT)))
        right=QVBoxLayout(); layout.addLayout(right,3); self.heading=QLabel('Learning diary'); self.heading.setObjectName('heading'); right.addWidget(self.heading)
        self.tabs=QTabWidget(); right.addWidget(self.tabs); self.widgets={}
        for tab,fields in [('Diary',['day','title','notes','reflection']),('Composition',['composition']),('Curriculum',['curriculum']),('Voyager mission',['mission'])]:
            page=QWidget(); form=QFormLayout(page)
            for f in fields:
                w=QLineEdit() if f in ['day','title'] else QPlainTextEdit(); self.widgets[f]=w; form.addRow(f.capitalize(),w); w.textChanged.connect(self.changed)
            self.tabs.addTab(page,tab)
        page=QWidget(); ml=QVBoxLayout(page); self.assets=QListWidget(); ml.addWidget(self.assets); self.preview=QLabel('Select an image to preview'); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumHeight(200); ml.addWidget(self.preview); self.assets.currentItemChanged.connect(self.show_media)
        for label,fn in [('Attach images / videos / audio',self.add_media),('Open selected file',self.open_media)]:
            b=QPushButton(label); b.clicked.connect(fn); ml.addWidget(b)
        self.tabs.addTab(page,'Media'); self.refresh(); self.statusBar().showMessage('Local journal ready')
    def changed(self):
        if not self.loading: self.dirty=True
    def refresh(self):
        self.list.blockSignals(True); self.list.clear()
        for r in DB.execute('SELECT * FROM entries ORDER BY day DESC,id DESC'):
            i=QListWidgetItem(r['day']+'  '+r['title']); i.setData(Qt.UserRole,r['id']); self.list.addItem(i)
        self.list.blockSignals(False)
        if self.list.count():
            idx=next((i for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole)==self.eid),0); self.list.setCurrentRow(idx)
    def select(self,item,old):
        if not item:return
        if self.dirty and self.eid is not None: self.save(False)
        self.eid=item.data(Qt.UserRole); r=DB.execute('SELECT * FROM entries WHERE id=?',(self.eid,)).fetchone(); self.loading=True
        for f,w in self.widgets.items():
            if isinstance(w,QLineEdit):w.setText(r[f] or '')
            else:w.setPlainText(r[f] or '')
        self.loading=False; self.dirty=False; self.load_media()
    def values(self):return {f:(w.text() if isinstance(w,QLineEdit) else w.toPlainText()) for f,w in self.widgets.items()}
    def save(self,refresh=True):
        if self.eid is None:return
        v=self.values(); DB.execute('UPDATE entries SET '+','.join(f+'=?' for f in FIELDS)+' WHERE id=?', [v[f] for f in FIELDS]+[self.eid]); DB.commit(); self.dirty=False; self.statusBar().showMessage('Saved',3000)
        if refresh:self.refresh()
    def new(self):
        self.save(False); self.eid=DB.execute('INSERT INTO entries(day,title) VALUES(?,?)',(date.today().isoformat(),'New lesson')).lastrowid; DB.commit(); self.refresh()
    def load_media(self):
        self.assets.clear(); self.preview.clear()
        for r in DB.execute('SELECT * FROM media WHERE entry_id=?',(self.eid,)):
            i=QListWidgetItem(r['name']); i.setData(Qt.UserRole,str(MEDIA/r['path'])); self.assets.addItem(i)
    def add_media(self):
        if self.eid is None:return
        paths,_=QFileDialog.getOpenFileNames(self,'Attach practice evidence','','Media (*.png *.jpg *.jpeg *.webp *.mov *.mp4 *.wav *.mp3 *.m4a *.pdf);;All files (*)')
        for p in paths:
            try:attach(self.eid,p)
            except OSError as e:QMessageBox.warning(self,'Attachment failed',str(e))
        self.load_media()
    def show_media(self,item,old):
        self.preview.clear()
        if item:
            pix=QPixmap(item.data(Qt.UserRole)); self.preview.setPixmap(pix.scaled(550,300,Qt.KeepAspectRatio,Qt.SmoothTransformation)) if not pix.isNull() else self.preview.setText('Use Open selected file to play or view this attachment.')
    def open_media(self):
        i=self.assets.currentItem()
        if i:QDesktopServices.openUrl(QUrl.fromLocalFile(i.data(Qt.UserRole)))
    def export(self):
        self.save(False); p,_=QFileDialog.getSaveFileName(self,'Export AI brief','voyager-brief.json','JSON (*.json)')
        if p:
            data={'entry_id':self.eid,**self.values(),'attachments':[r['name'] for r in DB.execute('SELECT name FROM media WHERE entry_id=?',(self.eid,))],'request':'Review attached evidence, suggest an original composition and curriculum. Return JSON with entry_id, composition, curriculum, reflection, mission. Do not invent performance observations.'}; Path(p).write_text(json.dumps(data,indent=2),encoding='utf-8'); QMessageBox.information(self,'Exported','Upload this JSON and the relevant media to ChatGPT. Media are not embedded in JSON.')
    def import_ai(self):
        p,_=QFileDialog.getOpenFileName(self,'Import AI response','','JSON (*.json)')
        if not p:return
        try:
            d=json.loads(Path(p).read_text(encoding='utf-8')); assert isinstance(d,dict) and d.get('entry_id')==self.eid, 'Response must match selected entry ID'; updates={f:d[f] for f in ['composition','curriculum','reflection','mission'] if isinstance(d.get(f),str)}; assert updates,'No supported fields found'
            if QMessageBox.question(self,'Apply AI response','Append AI suggestions to selected entry?')!=QMessageBox.Yes:return
            for f,v in updates.items():self.widgets[f].appendPlainText('\nAI suggestion:\n'+v)
            self.save()
        except Exception as e:QMessageBox.warning(self,'Invalid response',str(e))
    def closeEvent(self,event):self.save(False); event.accept()
app=QApplication(sys.argv); app.setOrganizationName('Voyager'); app.setApplicationName('GuitarDiary'); app.setStyle('Fusion'); app.setStyleSheet('QMainWindow,QWidget{background:#141b29;color:#e6edf5;font-size:14px} QLineEdit,QPlainTextEdit,QListWidget{background:#202b3d;border:1px solid #38475d;padding:7px} QPushButton{background:#294763;border:1px solid #456784;padding:9px;border-radius:5px} QPushButton:hover{background:#396482} QTabBar::tab{padding:10px;background:#202b3d} QTabBar::tab:selected{background:#36516e} QLabel#heading{font-size:25px;font-weight:bold} QListWidget::item:selected{background:#36516e}'); w=Window(); w.show(); sys.exit(app.exec())
