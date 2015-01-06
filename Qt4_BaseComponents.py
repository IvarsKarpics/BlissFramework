#
#  Project: MXCuBE
#  https://github.com/mxcube.
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with MXCuBE.  If not, see <http://www.gnu.org/licenses/>.

import logging
import pprint
import types
import os
import sys
import new
import time
import operator
import weakref
import gc

from PyQt4 import QtCore
from PyQt4 import QtGui

from HardwareRepository import HardwareRepository
from HardwareRepository.BaseHardwareObjects import HardwareObject
from BlissFramework.Utils import PropertyBag
from BlissFramework.Utils import Connectable
from BlissFramework.Utils import Qt4_ProcedureWidgets
from BlissFramework.Utils import Qt4_widget_colors
import BlissFramework

try:
  from louie import dispatcher
  from louie import saferef
except ImportError:
  from pydispatch import dispatcher
  from pydispatch import saferef
  saferef.safe_ref = saferef.safeRef

_emitterCache = weakref.WeakKeyDictionary()

class _QObject(QtCore.QObject):
    def __init__(self, *args, **kwargs):
        QtCore.QObject.__init__(self, *args)

        try:
            self.__ho = weakref.ref(kwargs.get("ho"))
        except:
            self.__ho = None

def emitter(ob):
    """Returns a QObject surrogate for *ob*, to use in Qt signaling.
       This function enables you to connect to and emit signals from (almost)
       any python object with having to subclass QObject.
    """
    if ob not in _emitterCache:
        _emitterCache[ob] = _QObject(ho=ob)
    return _emitterCache[ob]

class InstanceEventFilter(QtCore.QObject):
    def eventFilter(self, w, e):
        obj=w
        while obj is not None:
            if isinstance(obj,BlissWidget):
                if isinstance(e,QtCore.QContextMenuEvent):
                    #if obj.shouldFilterEvent():
                    #    return True
                    return True
                elif isinstance(e,QtCore.QMouseEvent):
                    if e.button()==Qt.RightButton:
                        return True
                    elif obj.shouldFilterEvent():
                        return True
                elif isinstance(e,QtCore.QKeyEvent) or isinstance(e,QtCore.QFocusEvent):
                    if obj.shouldFilterEvent():
                        return True
                return QtCore.QObject.eventFilter(self,w,e)
            #try:
            if True:
                obj=obj.parent()
            #except:
            #    obj=None
        return QtCore.QObject.eventFilter(self,w,e)


class WeakMethodBound:
    def __init__(self , f):
        self.f = weakref.ref(f.im_func)
        self.c = weakref.ref(f.im_self)
    def __call__(self , *args):
        obj = self.c()
        if obj is None:
            return None
        else:
            f=self.f()
            return f.__get__(obj)

class WeakMethodFree:
    def __init__(self , f):
        self.f = weakref.ref(f)
    def __call__(self, *args):
        return self.f()

def WeakMethod(f):
    try:
        f.im_func
    except AttributeError :
        return WeakMethodFree(f)
    return WeakMethodBound(f)


class SignalSlotFilter:
    def __init__(self, signal, slot, should_cache):
      self.signal = signal
      self.slot = WeakMethod(slot)
      self.should_cache = should_cache

    def __call__(self, *args):
        if BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_SLAVE and BlissWidget._instanceMirror==BlissWidget.INSTANCE_MIRROR_PREVENT:
           if self.should_cache:
               BlissWidget._eventsCache[self.slot]=(time.time(), self.slot, args)
               return

        s = self.slot()
        if s is not None:
            s(*args)


class BlissWidget(QtGui.QWidget, Connectable.Connectable):
    (INSTANCE_ROLE_UNKNOWN,INSTANCE_ROLE_SERVER,INSTANCE_ROLE_SERVERSTARTING,INSTANCE_ROLE_CLIENT,INSTANCE_ROLE_CLIENTCONNECTING) = (0,1,2,3,4)
    (INSTANCE_MODE_UNKNOWN,INSTANCE_MODE_MASTER,INSTANCE_MODE_SLAVE) = (0,1,2)
    (INSTANCE_LOCATION_UNKNOWN,INSTANCE_LOCATION_LOCAL,INSTANCE_LOCATION_INHOUSE,INSTANCE_LOCATION_INSITE,INSTANCE_LOCATION_EXTERNAL) = (0,1,2,3,4)
    (INSTANCE_USERID_UNKNOWN,INSTANCE_USERID_LOGGED,INSTANCE_USERID_INHOUSE,INSTANCE_USERID_IMPERSONATE) = (0,1,2,3)
    (INSTANCE_MIRROR_UNKNOWN,INSTANCE_MIRROR_ALLOW,INSTANCE_MIRROR_PREVENT) = (0,1,2)

    _runMode = False
    _instanceRole = INSTANCE_ROLE_UNKNOWN
    _instanceMode = INSTANCE_MODE_UNKNOWN
    _instanceLocation = INSTANCE_LOCATION_UNKNOWN
    _instanceUserId = INSTANCE_USERID_UNKNOWN
    _instanceMirror = INSTANCE_MIRROR_UNKNOWN
    _filterInstalled = False
    _eventsCache = {}
    _menuBackgroundColor = None
    _menuBar = None

    _applicationEventFilter=InstanceEventFilter(None)
    
    @staticmethod
    def setRunMode(mode):
        if mode:
            BlissWidget._runMode = True
            for w in QtGui.QApplication.allWidgets():
                if isinstance(w, BlissWidget):
                    w.__run()
                    try:
                        w.setExpertMode(False)
                    except:
                        logging.getLogger().exception("Could not set %s to user mode", w.name())

        else:
            BlissWidget._runMode = False
            for w in QtGui.QApplication.allWidgets():
                if isinstance(w, BlissWidget):
                    w.__stop()
                    try:
                        w.setExpertMode(True)
                    except:
                        logging.getLogger().exception("Could not set %s to expert mode", w.name())


    @staticmethod
    def isRunning():
        return BlissWidget._runMode


    @staticmethod
    def updateMenuBarColor(enable_checkbox=None):
        color=None
        if BlissWidget._menuBar is not None:
            if BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER:
                if BlissWidget._instanceUserId==BlissWidget.INSTANCE_USERID_IMPERSONATE:
                    color=Qt4_widget_colors.LIGHT_BLUE
                else:
                    color=Qt4_widget_colors.LIGHT_GREEN
            elif BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_SLAVE:
                if BlissWidget._instanceRole==BlissWidget.INSTANCE_ROLE_CLIENTCONNECTING:
                    color=Qt4_widget_colors.LIGHT_RED
                elif BlissWidget._instanceUserId==BlissWidget.INSTANCE_USERID_UNKNOWN:
                    color=QtGui.QColor(255,165,0)
                else:
                    color=Qt4_widget_colors.LIGHT_YELLOW
        if color is not None:
            BlissWidget._menuBar.setPaletteBackgroundColor(color)
            children = BlissWidget._menuBar.children() or []
            for child in children:
                if isinstance(child,QCheckBox):
                    child.setPaletteBackgroundColor(color)
                    if enable_checkbox is not None:
                        child.setEnabled(enable_checkbox)
                        if enable_checkbox and child.isChecked():
                            child.setPaletteBackgroundColor(Qt.yellow)


    @staticmethod
    def setInstanceMode(mode):
        BlissWidget._instanceMode = mode

        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                #try:
                w._instanceModeChanged(mode)
                #except:
                #    pass

        if BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER:
            if BlissWidget._filterInstalled:
                QtGui.QApplication.removeEventFilter(BlissWidget._applicationEventFilter)
                BlissWidget._filterInstalled = False
                BlissWidget.synchronizeWithCache() # why?
        else:
            if not BlissWidget._filterInstalled:
                QtGui.QApplication.installEventFilter(BlissWidget._applicationEventFilter)
                BlissWidget._filterInstalled = True

        BlissWidget.updateMenuBarColor(BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER)


    def shouldFilterEvent(self):
        if BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER:
            return False
        try:
            allow_always=self['instanceAllowAlways']
        except KeyError:
            return False
        if not allow_always:
            try:
                allow_connected=self['instanceAllowConnected']
            except KeyError:
                return False

            connected = BlissWidget._instanceRole in (BlissWidget.INSTANCE_ROLE_SERVER,BlissWidget.INSTANCE_ROLE_CLIENT)
            if allow_connected and connected:
                return False
            return True

        return False


    def connectGroupBox(self,widget,widget_name,masterSync):
        brick_name = self.name()
        self.connect(widget, QtCore.SIGNAL('toggled(bool)'),lambda s:BlissWidget.widgetGroupBoxToggled(brick_name,widget_name, masterSync,s))


    def connectComboBox(self,widget,widget_name,masterSync):
        brick_name = self.name()
        self.connect(widget, QtCore.SIGNAL('activated(int)'),lambda i:BlissWidget.widgetComboBoxActivated(brick_name,widget_name,widget,masterSync, i))


    def connectLineEdit(self,widget,widget_name,masterSync):
        brick_name = self.name()
        self.connect(widget, QtCore.SIGNAL('textChanged(const QString &)'),lambda t:BlissWidget.widgetLineEditTextChanged(brick_name,widget_name,masterSync,t))


    def connectSpinBox(self,widget,widget_name,masterSync):
        brick_name = self.name()
        self.connect(widget, QtCore.SIGNAL('editorTextChanged'),lambda t:BlissWidget.widgetSpinBoxTextChanged(brick_name,widget_name,masterSync,t))
        #self.connect(widget,SIGNAL('valueChanged(const QString &)'),lambda v:BlissWidget.widgetSpinBoxValueChanged(self,widget_name,v))


    def connectGenericWidget(self,widget,widget_name,masterSync):
        brick_name = self.name()
        self.connect(widget, QtCore.SIGNAL('widgetSynchronize'),lambda state:BlissWidget.widgetGenericChanged(brick_name,widget_name,masterSync,state))


    def _instanceModeChanged(self,mode):
        for widget,widget_name,masterSync in self._widgetEvents:
            if isinstance(widget, QtHui.QGroupBox):
                self.connectGroupBox(widget,widget_name,masterSync)
            elif isinstance(widget,QtGui.QComboBox):
                self.connectComboBox(widget,widget_name,masterSync)
            elif isinstance(widget, QtGui.QLineEdit):
                self.connectLineEdit(widget,widget_name,masterSync)
            elif isinstance(widget, QtGui.QSpinBox):
                self.connectSpinBox(widget,widget_name,masterSync)
            else:
                ### verify if widget has the widgetSynchronize method!!!
                self.connectGenericWidget(widget,widget_name,masterSync)
        self._widgetEvents=[]

        if self.shouldFilterEvent():
            self.setCursor(QtGui.QCursor(QtCore.Qt.ForbiddenCursor))
        else:
            self.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))

        self.instanceModeChanged(mode)


    def instanceModeChanged(self,mode):
        pass


    @staticmethod
    def isInstanceModeMaster():
        return BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER


    @staticmethod
    def isInstanceModeSlave():
        return BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_SLAVE


    @staticmethod
    def isInstanceRoleUnknown():
        return BlissWidget._instanceRole==BlissWidget.INSTANCE_ROLE_UNKNOWN


    @staticmethod
    def isInstanceRoleClient():
        return BlissWidget._instanceRole==BlissWidget.INSTANCE_ROLE_CLIENT


    @staticmethod
    def isInstanceRoleServer():
        return BlissWidget._instanceRole==BlissWidget.INSTANCE_ROLE_SERVER


    @staticmethod
    def isInstanceUserIdUnknown():
        return BlissWidget._instanceUserId==BlissWidget.INSTANCE_USERID_UNKNOWN


    @staticmethod
    def isInstanceUserIdLogged():
        return BlissWidget._instanceUserId==BlissWidget.INSTANCE_USERID_LOGGED


    @staticmethod
    def isInstanceUserIdInhouse():
        return BlissWidget._instanceUserId==BlissWidget.INSTANCE_USERID_INHOUSE


    @staticmethod
    def setInstanceRole(role):
        if role==BlissWidget._instanceRole:
            return
        BlissWidget._instanceRole = role
        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                try:
                    w.instanceRoleChanged(role)
                except:
                    pass


    @staticmethod
    def setInstanceLocation(location):
        if location==BlissWidget._instanceLocation:
            return
        BlissWidget._instanceLocation = location
        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                try:
                    w.instanceLocationChanged(location)
                except:
                    pass


    @staticmethod
    def setInstanceUserId(user_id):
        if user_id==BlissWidget._instanceUserId:
            return
        BlissWidget._instanceUserId = user_id

        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                try:
                    w.instanceUserIdChanged(user_id)
                except:
                    pass

        BlissWidget.updateMenuBarColor()


    @staticmethod
    def setInstanceMirror(mirror):
        if mirror==BlissWidget._instanceMirror:
            return
        BlissWidget._instanceMirror = mirror

        if mirror==BlissWidget.INSTANCE_MIRROR_ALLOW:
            BlissWidget.synchronizeWithCache()

        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                try:
                    w.instanceMirrorChanged(mirror)
                except:
                    pass

        #BlissWidget.updateMenuBarColor()


    def instanceMirrorChanged(self,mirror):
        pass

    
    def instanceLocationChanged(self,location):
        pass


    @staticmethod
    def isInstanceLocationUnknown():
        return BlissWidget._instanceLocation==BlissWidget.INSTANCE_LOCATION_UNKNOWN


    @staticmethod
    def isInstanceLocationLocal():
        return BlissWidget._instanceLocation==BlissWidget.INSTANCE_LOCATION_LOCAL


    @staticmethod
    def isInstanceMirrorAllow():
        return BlissWidget._instanceMirror==BlissWidget.INSTANCE_MIRROR_ALLOW


    def instanceUserIdChanged(self,user_id):
        pass


    def instanceRoleChanged(self,role):
        pass


    @staticmethod
    def updateWhatsThis():
        for w in QtGui.QApplication.allWidgets():
            if isinstance(w, BlissWidget):
                QtGui.QWhatsThis.remove(w)
                QtGui.QWhatsThis.add(w, "%s (%s)\n%s" % (w.name(), w.__class__.__name__, w.getHardwareObjectsInfo()))
        QtGui.QWhatsThis.enterWhatsThisMode()


    @staticmethod
    def updateWidget(brick_name,widget_name,method_name,method_args,masterSync):
        #logging.getLogger().debug("------------------------- UPDATE WIDGET, masterSync=%s", masterSync)
        if not masterSync or BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER:
            QtGui.QApplication.mainWidget().emit(QtCore.SIGNAL('applicationBrickChanged'),(brick_name,widget_name,method_name,method_args,masterSync))


    @staticmethod
    def updateTabWidget(tab_name,tab_index):
        if BlissWidget._instanceMode==BlissWidget.INSTANCE_MODE_MASTER:
            QtGui.QApplication.mainWidget().emit(QtCore.SIGNAL('applicationTabChanged'),(tab_name,tab_index))


    @staticmethod
    def widgetGroupBoxToggled(brick_name,widget_name,masterSync,state):
        BlissWidget.updateWidget(brick_name,widget_name,"setChecked",(state,),masterSync)


    @staticmethod
    def widgetComboBoxActivated(brick_name, widget_name,widget,masterSync,index):
        lines=[]
        if widget.editable():
            for i in range(widget.count()):
                lines.append(str(widget.text(i)))
        BlissWidget.updateWidget(brick_name,widget_name,"activated",(index,lines),masterSync)


    @staticmethod
    def widgetLineEditTextChanged(brick_name,widget_name,masterSync,text):
        BlissWidget.updateWidget(brick_name,widget_name,"setText",(str(text),),masterSync)


    @staticmethod
    def widgetSpinBoxTextChanged(brick_name,widget_name,masterSync,text):
        BlissWidget.updateWidget(brick_name,widget_name,"setEditorText",(str(text),), masterSync)


    @staticmethod
    def widgetGenericChanged(brick_name,widget_name,masterSync,state):
        BlissWidget.updateWidget(brick_name,widget_name,"widgetSynchronize",(state,),masterSync)


    def instanceForwardEvents(self,widget_name,masterSync):
        if widget_name=="":
            widget=self
        else:
            widget=getattr(self, widget_name)
        if isinstance(widget, QtGui.QComboBox):
            widget.activated = new.instancemethod(ComboBoxActivated,widget,widget.__class__)
        elif isinstance(widget, QtGui.QSpinBox):
            widget.setEditorText = new.instancemethod(SpinBoxSetEditorText,widget,widget.__class__)
            widget.editorTextChanged = new.instancemethod(SpinBoxEditorTextChanged,widget,widget.__class__)
            self.connect(widget.lineEdit(), QtCore.SIGNAL('textChanged(const QString &)'), widget.editorTextChanged)
        self._widgetEvents.append((widget, widget_name, masterSync))


    def instanceSynchronize(self,*args, **kwargs):
        for widget_name in args:
            self.instanceForwardEvents(widget_name, kwargs.get("masterSync", True))


    @staticmethod
    def shouldRunEvent():
        return BlissWidget._instanceMirror==BlissWidget.INSTANCE_MIRROR_ALLOW


    @staticmethod
    def addEventToCache(timestamp,method,*args):
        try:
            m = WeakMethod(method)
        except TypeError:
            m = method
        BlissWidget._eventsCache[m]=(timestamp, m, args)


    @staticmethod
    def synchronizeWithCache():
        events=BlissWidget._eventsCache.values()
        ordered_events=sorted(events,key=operator.itemgetter(0))
        for event_timestamp,event_method,event_args in ordered_events:
            try:
                m = event_method()
                if m is not None:
                  m(*event_args)
            except:
                pass
        BlissWidget._eventsCache={}


    def __init__(self, parent = None, widgetName = ''):       
        Connectable.Connectable.__init__(self)
        QtGui.QWidget.__init__(self, parent)
        self.setObjectName(widgetName)

        ##self.setSizePolicy(QtGui.QSizePolicy.MinimumExpanding, \
        ##                   QtGui.QSizePolicy.MinimumExpanding)
        self.propertyBag = PropertyBag.PropertyBag()
                
        self.__enabledState = True #saved enabled state
        self.__loadedHardwareObjects = []
        self._signalSlotFilters = {}
        self._widgetEvents = []
 
        #
        # add what's this help
        #
        self.setWhatsThis("%s (%s)\n" % (widgetName, self.__class__.__name__))
        #WhatsThis.add(self, "%s (%s)\n" % (widgetName, self.__class__.__name__))
        
        #
        # add properties shared by all BlissWidgets
        #
        self.addProperty('fontSize', 'string', str(self.font().pointSize()))
        #self.addProperty("alignment", "combo", ("none", "top center", "top left", "top right", "bottom center", "bottom left", "bottom right", "center", "left", "right"), "none")
        self.addProperty('instanceAllowAlways', 'boolean', False)#, hidden=True)
        self.addProperty('instanceAllowConnected', 'boolean', False)#, hidden=True)

        #
        # connect signals / slots
        #
        dispatcher.connect(self.__hardwareObjectDiscarded, 'hardwareObjectDiscarded', HardwareRepository.HardwareRepository())
 
        self.defineSlot('enable_widget', ())

    def __run(self):
        self.setAcceptDrops(False)

        #
        # put it back to a normal state
        #
        self.blockSignals(False)
        
        self.setEnabled(self.__enabledState)
 
        #import sys, gc, types
        
        try:        
            self.run()
        except:
            logging.getLogger().exception("Could not set %s to run mode", self.objectName())


    def __stop(self):
        self.blockSignals(True)
        
        try:
            self.stop()       
        except:
            logging.getLogger().exception("Could not stop %s", self.objectName())

        #self.setAcceptDrops(True)
        self.__enabledState = self.isEnabled()
        QtGui.QWidget.setEnabled(self, True)
       

    def __repr__(self):
        return repr("<%s: %s>" % (self.__class__, self.objectName))


    def connectSignalSlotFilter(self,sender,signal,slot,should_cache):
        uid=(sender, signal, hash(slot))
	signalSlotFilter = SignalSlotFilter(signal, slot, should_cache)
        self._signalSlotFilters[uid]=signalSlotFilter

	QtCore.QObject.connect(sender, signal, signalSlotFilter)


    def connect(self, sender, signal, slot, instanceFilter=False, shouldCache=True):
	signal = str(signal)
        if signal[0].isdigit():
          pysignal = signal[0]=='9'
          signal=signal[1:]
        else:
          pysignal=True

        if not isinstance(sender, QtCore.QObject):
          if isinstance(sender, HardwareObject):
            #logging.warning("You should use %s.connect instead of using %s.connect", sender, self)
            sender.connect(signal, slot) 
            return
          else:
            _sender = emitter(sender)
        else:
	    _sender = sender

        if instanceFilter:
            self.connectSignalSlotFilter(_sender, pysignal and PYSIGNAL(signal) or SIGNAL(signal), slot, shouldCache)
        else:
            QtCore.QObject.connect(_sender, pysignal and QtCore.SIGNAL(signal) or QtCore.SIGNAL(signal), slot)

        # workaround for PyQt lapse
        if hasattr(sender, "connectNotify"):
            sender.connectNotify(QtCore.SIGNAL(signal))
    

    def disconnect(self, sender, signal, slot):
	signal = str(signal)
        if signal[0].isdigit():
          pysignal = signal[0]=='9'
          signal=signal[1:]
        else:
          pysignal=True

        if isinstance(sender, HardwareObject):
          #logging.warning("You should use %s.disconnect instead of using %s.connect", sender,self)
          sender.disconnect(signal, slot)
          return

        # workaround for PyQt lapse
        if hasattr(sender, "disconnectNotify"):
            sender.disconnectNotify(signal)

        if not isinstance(sender, QObject):
            sender = emitter(sender)
           
            try:
                uid=(sender, pysignal and QtCore.SIGNAL(signal) or QtCore.SIGNAL(signal), hash(slot))
                signalSlotFilter=self._signalSlotFilters[uid]
            except KeyError:
                QtCore.QObject.disconnect(sender, pysignal and QtCore.SIGNAL(signal) or QtCore.SIGNAL(signal), slot)
            else:
                QtCore.QObject.disconnect(sender, pysignal and QtCore.SIGNAL(signal) or QtCore.SIGNAL(signal), signalSlotFilter)
                del self._signalSlotFilters[uid]
        else:
            QtCore.QObject.disconnect(sender, pysignal and QtCore.SIGNAL(signal) or QtCore.SIGNAL(signal), signalSlotFilter)


    def reparent(self, widget_to):
        savedEnabledState = self.isEnabled()
        if self.parent() is not None:
            self.parent().layout().removeWidget(self)
        if widget_to is not None:
            widget_to.layout().addWidget(self)
            self.setEnabled(savedEnabledState)
        
    def blockSignals(self, block):
        for child in self.children():
            child.blockSignals(block)
            
                
    def run(self):
        pass


    def stop(self):
        pass

    
    def restart(self):
        self.stop()
        self.run()
              

    def loadUIFile(self, filename):
        for path in [BlissFramework.getStdBricksPath()]+BlissFramework.getCustomBricksDirs():
          #modulePath = sys.modules[self.__class__.__module__].__file__
          #path = os.path.dirname(modulePath)
          if os.path.exists(os.path.join(path, filename)):
            return qtui.QWidgetFactory.create(os.path.join(path, filename))


    def createGUIFromUI(self, UIFile):
        widget = self.loadUIFile(UIFile)

        if widget is not None:
            children = self.children() or []
            for child in children:
                self.removeChild(child) # remove all children first
                
            layout = QtGui.QGridLayout(self, 1, 1)
            widget.reparent(self)
            widget.show()
            layout.addWidget(widget, 0, 0)
            self.setLayout(layout)
            return widget

  
    def setPersistentPropertyBag(self, persistentPropertyBag):
        if id(persistentPropertyBag) != id(self.propertyBag):
            for property in persistentPropertyBag:
                #
                # persistent properties are set
                # 
                if property.getName() in self.propertyBag.properties:
                    self.propertyBag.getProperty(property.getName()).setValue(property.getUserValue())
                elif property.hidden:
                    self.propertyBag[property.getName()] = property
        
        self.readProperties()
                            
           
    def readProperties(self):
        for prop in self.propertyBag:
            self._propertyChanged(prop.getName(), None, prop.getUserValue())
        
    """
    def editProperties(self):
        if not self.propertyBag.isEmpty():
            editor = self.propertyBag.editor()
            self.connect(editor, PYSIGNAL('propertyChanged'), self._propertyChanged)
            editor.exec_loop()
    """

    def addProperty(self, *args, **kwargs):
        self.propertyBag.addProperty(*args, **kwargs)
               

    def getProperty(self, propertyName):
        return self.propertyBag.getProperty(propertyName)


    def showProperty(self, propertyName):
        return self.propertyBag.showProperty(propertyName)


    def hideProperty(self, propertyName):
        return self.propertyBag.hideProperty(propertyName)


    def delProperty(self, propertyName):
        return self.propertyBag.delProperty(propertyName)
    

    def getHardwareObject(self, hardwareObjectName):
        if not hardwareObjectName in self.__loadedHardwareObjects:
            self.__loadedHardwareObjects.append(hardwareObjectName)

        ho = HardwareRepository.HardwareRepository().getHardwareObject(hardwareObjectName)
    
        return ho
        

    def __hardwareObjectDiscarded(self, hardwareObjectName):
        if hardwareObjectName in self.__loadedHardwareObjects:
            # there is a high probability we need to reload this hardware object...
            self.readProperties() #force to read properties


    def getHardwareObjectsInfo(self):
        d = {}
        
        for ho_name in self.__loadedHardwareObjects:
            info = HardwareRepository.HardwareRepository().getInfo(ho_name)
            
            if len(info) > 0:
                d[ho_name] = info

        if len(d):
            return "Hardware Objects:\n\n%s" % pprint.pformat(d)
        else:
            return ""
        

    def __getitem__(self, propertyName):
        #
        # direct access to properties values
        #
        return self.propertyBag[propertyName]
        

    def __setitem__(self, propertyName, value):
        p = self.propertyBag.getProperty(propertyName)
        oldValue = p.getValue()
        p.setValue(value)

        self._propertyChanged(propertyName, oldValue, p.getUserValue())
                    
    
    def _propertyChanged(self, propertyName, oldValue, newValue):
        #import time; t0=time.time()    
        if propertyName == 'fontSize':
            try:
                s = int(newValue)
            except:
                self.getProperty('fontSize').setValue(self.font().pointSize())
            else:
                f = self.font()
                f.setPointSize(s)
                self.setFont(f)

                #for brick in self.queryList("QWidget"):
                for brick in self.children():
                    if isinstance(brick, BlissWidget):
                        brick["fontSize"] = s
                
                self.update()
        else:
            try:
                self.propertyChanged(propertyName, oldValue, newValue)
            except:
                logging.getLogger().exception('Error while setting property %s for %s (details in log file).', propertyName, str(self.objectName()))

        #if not BlissWidget.isRunning():
        #    self.blockSignals(True)
        

    def propertyChanged(self, propertyName, oldValue, newValue):
        pass


    def setExpertMode(self, expert):
        pass
    
    def enable_widget(self, state):
      if state:
        self.setEnabled(True)
      else:
        self.setDisabled(True)
  
class NullBrick(BlissWidget):
    def __init__(self, *args):
        BlissWidget.__init__(self, *args)

        self.propertyBag = PropertyBag.PropertyBag()

    """
    def setShelf(self, shelf):
        persistentPropertyBag = PropertyBag.unpickleFromShelf(shelf, self.name())

        if not persistentPropertyBag.isEmpty():       
            for property in persistentPropertyBag:
                #
                # persistent properties are set
                # 
                self.propertyBag[property.getName()] = property
    """
    def setPersistentPropertyBag(self, persistentPropertyBag):
        self.propertyBag = persistentPropertyBag
        
    
    def sizeHint(self):
        return QtCore.QSize(100, 100)  


    def run(self):
        self.hide()


    def stop(self):
        self.show()


    def paintEvent(self, event):
        if not self.isRunning():
            p = QtGui.QPainter(self)
            p.setPen(QtGui.QPen(QtCore.Qt.black, 1))
            p.drawLine(0, 0, self.width(), self.height())
            p.drawLine(0, self.height(), self.width(), 0)
  

class ProcedureBrick(BlissWidget):
    def __init__(self, *args):
        BlissWidget.__init__(self, *args)

        self.__pages = []
    
        #
        # add properties
        #
        self.addProperty('mnemonic', 'string', '')
        self.addProperty('equipment', 'string', '')

        #
        # create GUI elements
        #
        from BlissFramework.Utils.RunStopPanel import RunStopPanel
        self.procedureTab = QTabWidget(self)
        self.runStopPanel = RunStopPanel(self)
     
        #
        # configure GUI elements
        #
        self.procedureTab.setTabShape(QTabWidget.Triangular)

        #
        # connect signals / slots
        #
        self.connect(self.runStopPanel, PYSIGNAL('launch'), self.launchProcedure)
        self.connect(self.runStopPanel, PYSIGNAL('stop'), self.stopProcedure)

        #
        # layout
        #
        ##self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)

        QVBoxLayout(self, 10, 10)
        self.layout().addWidget(self.procedureTab, 0)
        self.layout().addWidget(self.runStopPanel, 0, Qt.AlignRight | Qt.AlignBottom)        


    def setMnemonic(self, mne):
        self.getProperty('mnemonic').setValue(mne)

 	proc = HardwareRepository.HardwareRepository().getProcedure(mne)

	self.__setProcedure(proc)


    def __setProcedure(self, proc):
        for p in self.__pages:
            p.setProcedure(proc)

        self.setProcedure(proc)
        
    
    def setProcedure(self, proc):
        pass

    
    def setEquipmentMnemonic(self, mne):
        self.getProperty('equipment').setValue(mne)
        
        e = self.getHardwareObject(mne)
        
        self.setEquipment(e)


    def setEquipment(self, equipment):
        pass
    
        
    def launchProcedure(self):
        pass


    def stopProcedure(self):
        pass
    

    def dataFileChanged(self, filename):
        pass
    
            
    def addPage(self, pageName):
        self.__pages.append(Qt4_ProcedureWidgets.ProcedurePanel(self))

        self.__pages[-1].setProcedure(HardwareRepository.HardwareRepository().getProcedure(self['mnemonic']))
        self.procedureTab.addTab(self.__pages[-1], pageName)

        return self.__pages[-1]


    def showPage(self, page):
        self.procedureTab.showPage(page)
        
        
    def propertyChanged(self, property, oldValue, newValue):
        if property == 'mnemonic':
       	    self.setMnemonic(newValue) #Procedure(HardwareRepository.HardwareRepository().getHardwareObject(newValue))
        elif property == 'equipment':
            self.setEquipment(self.getHardwareObject(newValue))


def ComboBoxActivated(self,index,lines):
    if self.editable():
        #lines=state[1]
        last=self.count()
        if index>=last:
            i=index
            while True:
                try:
                    line=lines[i]
                except:
                    break
                else:
                    self.insertItem(line)
                    self.setCurrentItem(i)
                    self.emit(QtCore.SIGNAL('activated(const QString &)'), (line,))
                    self.emit(QtCore.SIGNAL('activated(int)'), (i,))
                i+=1
    self.setCurrentItem(index)
    self.emit(QtCore.SIGNAL('activated(const QString &)'), (self.currentText(),))
    self.emit(QtCore.SIGNAL('activated(int)'), (index,))


def SpinBoxEditorTextChanged(self,t):
    self.emit(QtCore.SIGNAL('editorTextChanged'), (str(t),))
def SpinBoxSetEditorText(self,t):
    self.editor().setText(t)
