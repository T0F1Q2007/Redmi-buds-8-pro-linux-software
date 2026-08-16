import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

const DBUS_SERVICE = 'org.redmibuds8.Control';
const DBUS_PATH = '/org/redmibuds8/Control';


const DBusProxy = Gio.DBusProxy.makeProxyWrapper(`
<node>
    <interface name="org.redmibuds8.Control">
        <method name="SetAncMode">
            <arg type="i" name="mode" direction="in"/>
        </method>
        <method name="SetAncDepth">
            <arg type="i" name="depth" direction="in"/>
        </method>
        <method name="SetTransparencySubmode">
            <arg type="i" name="submode" direction="in"/>
        </method>
        <method name="SetEqMode">
            <arg type="i" name="mode" direction="in"/>
        </method>
        <method name="SetImmersiveCommute">
            <arg type="i" name="mode" direction="in"/>
        </method>
        <method name="SetInEarDetection">
            <arg type="b" name="enabled" direction="in"/>
        </method>
        <method name="SetAudioMode">
            <arg type="i" name="mode" direction="in"/>
        </method>
        <method name="SetHeadTracking">
            <arg type="b" name="enabled" direction="in"/>
        </method>
        <signal name="StateChanged"/>
        <property name="Connected" type="b" access="read"/>
        <property name="BatteryLeft" type="i" access="read"/>
        <property name="BatteryRight" type="i" access="read"/>
        <property name="BatteryCase" type="i" access="read"/>
        <property name="AncMode" type="i" access="read"/>
        <property name="AncDepth" type="i" access="read"/>
        <property name="TransparencySubmode" type="i" access="read"/>
        <property name="EqMode" type="i" access="read"/>
        <property name="ImmersiveCommute" type="i" access="read"/>
        <property name="InEarDetection" type="b" access="read"/>
        <property name="AudioMode" type="i" access="read"/>
        <property name="HeadTracking" type="b" access="read"/>
    </interface>
</node>
`);

const BudsIndicator = GObject.registerClass(
class BudsIndicator extends PanelMenu.Button {
    constructor() {
        super(0.0, 'Redmi Buds 8 Pro');
        
        this._icon = new St.Icon({
            icon_name: 'audio-headphones-symbolic',
            style_class: 'system-status-icon'
        });
        this.add_child(this._icon);

        this._proxy = null;
        this._signalId = 0;
        this._lockInEar = false;

        this._buildMenu();
        this._connectDBus();
    }

    async _connectDBus() {
        try {
            this._proxy = await new Promise((resolve, reject) => {
                new DBusProxy(
                    Gio.DBus.session,
                    DBUS_SERVICE,
                    DBUS_PATH,
                    (proxy, error) => {
                        if (error) {
                            reject(error);
                        } else {
                            resolve(proxy);
                        }
                    }
                );
            });

            this._signalId = this._proxy.connectSignal('StateChanged', () => {
                this._updateStateFromProxy();
            });

            this._updateStateFromProxy();
        } catch (e) {
            console.error('Failed to connect to Redmi Buds daemon:', e);
            this._batteryLabel.set_text('Daemon not connected');
        }
    }

    _updateStateFromProxy() {
        if (!this._proxy) return;

        try {
            // Update battery readout
            let l = this._proxy.BatteryLeft;
            let r = this._proxy.BatteryRight;
            let c = this._proxy.BatteryCase;

            let lTxt = l >= 0 ? `${l}%` : '--';
            let rTxt = r >= 0 ? `${r}%` : '--';
            let cTxt = c >= 0 ? `${c}%` : '--';

            let batteryText = `🎧 L: ${lTxt}  |  R: ${rTxt}  |  🔋 Case: ${cTxt}`;
            this._batteryLabel.set_text(batteryText);
            this.set_tooltip_text(`Redmi Buds 8 Pro (${batteryText})`);

            // Update ANC selection checkmarks
            let currentAnc = this._proxy.AncMode;
            let currentDepth = this._proxy.AncDepth;
            let currentTransSub = this._proxy.TransparencySubmode;

            this._ancItems.forEach(item => {
                let isSelected = item.modeValue === currentAnc;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
                item.setOrnament(isSelected ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            });

            // Update ANC depth / sub-mode visibility
            this._ancDepthSection.actor.visible = (currentAnc === 1);
            this._ancDepthItems.forEach(item => {
                let isSelected = item.depthValue === currentDepth;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
            });

            this._transSubSection.actor.visible = (currentAnc === 2);
            this._transSubItems.forEach(item => {
                let isSelected = item.submodeValue === currentTransSub;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
            });

            // Update EQ checkmarks
            let currentEq = this._proxy.EqMode;
            this._eqItems.forEach(item => {
                let isSelected = item.eqValue === currentEq;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
                item.setOrnament(isSelected ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            });

            // Update Commute checkmarks
            let currentCommute = this._proxy.ImmersiveCommute;
            this._commuteItems.forEach(item => {
                let isSelected = item.commuteValue === currentCommute;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
                item.setOrnament(isSelected ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            });

            // Update In-Ear Detection
            if (!this._lockInEar) {
                this._inEarToggle.setToggleState(this._proxy.InEarDetection);
            }

            // Update Audio Mode & Head Tracking
            let currentAudioMode = this._proxy.AudioMode;
            let currentHeadTracking = this._proxy.HeadTracking;

            this._audioModeItems.forEach(item => {
                let isSelected = item.audioValue === currentAudioMode;
                item.label.set_text((isSelected ? '✓ ' : '   ') + item.rawLabel);
                item.setOrnament(isSelected ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            });

            let modeName = 'Off';
            if (currentAudioMode === 1) modeName = 'Dolby Audio';
            if (currentAudioMode === 2) modeName = currentHeadTracking ? 'Xiaomi Immersive + Head Tracking' : 'Xiaomi Immersive';
            this._audioStatusLabel.set_text(`Current: ${modeName}`);

            this._headToggle.setToggleState(currentHeadTracking);
            this._headToggle.setSensitive(currentAudioMode === 2);
        } catch (e) {
            console.error('Error updating extension state from proxy:', e);
        }
    }

    _buildMenu() {
        // 1. Battery Header
        this._batteryLabel = new St.Label({
            text: 'Connecting...',
            style_class: 'buds-battery-header'
        });
        let batteryItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        batteryItem.add_child(this._batteryLabel);
        this.menu.addMenuItem(batteryItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 2. ANC Section
        let ancTitle = new PopupMenu.PopupMenuItem('Noise Control', { reactive: false });
        ancTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(ancTitle);

        this._ancItems = [];
        let ancModes = [
            { label: 'Off', value: 0 },
            { label: 'Noise Cancellation (ANC)', value: 1 },
            { label: 'Transparency', value: 2 }
        ];

        ancModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('   ' + mode.label);
            item.rawLabel = mode.label;
            item.modeValue = mode.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetAncModeRemote(mode.value);
                    this._updateStateFromProxy();
                }
            });
            this.menu.addMenuItem(item);
            this._ancItems.push(item);
        });

        // ANC Depth Sub-menu
        this._ancDepthSection = new PopupMenu.PopupSubMenuMenuItem('   ▸ ANC Depth Level');
        this._ancDepthItems = [];
        let ancDepths = [
            { label: 'Smart ANC (Adaptive)', value: 0 },
            { label: 'Deep ANC', value: 1 },
            { label: 'Balanced ANC', value: 2 },
            { label: 'Light ANC', value: 3 }
        ];
        ancDepths.forEach(depth => {
            let item = new PopupMenu.PopupMenuItem('   ' + depth.label);
            item.rawLabel = depth.label;
            item.depthValue = depth.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetAncDepthRemote(depth.value);
                    this._updateStateFromProxy();
                }
            });
            this._ancDepthSection.menu.addMenuItem(item);
            this._ancDepthItems.push(item);
        });
        this.menu.addMenuItem(this._ancDepthSection);

        // Transparency Sub-mode Sub-menu
        this._transSubSection = new PopupMenu.PopupSubMenuMenuItem('   ▸ Transparency Mode');
        this._transSubItems = [];
        let transSubmodes = [
            { label: 'Regular Transparency', value: 2 },
            { label: 'Enhanced Voice', value: 0 },
            { label: 'Enhanced Ambience Sound', value: 1 }
        ];
        transSubmodes.forEach(sub => {
            let item = new PopupMenu.PopupMenuItem('   ' + sub.label);
            item.rawLabel = sub.label;
            item.submodeValue = sub.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetTransparencySubmodeRemote(sub.value);
                    this._updateStateFromProxy();
                }
            });
            this._transSubSection.menu.addMenuItem(item);
            this._transSubItems.push(item);
        });
        this.menu.addMenuItem(this._transSubSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 3. EQ Section
        let eqTitle = new PopupMenu.PopupMenuItem('Equalizer (EQ)', { reactive: false });
        eqTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(eqTitle);

        this._eqItems = [];
        let eqModes = [
            { label: 'Standard', value: 1 },
            { label: 'Music', value: 2 },
            { label: 'Video', value: 3 },
            { label: 'Game', value: 4 },
            { label: 'Audio Books', value: 5 }
        ];

        eqModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('   ' + mode.label);
            item.rawLabel = mode.label;
            item.eqValue = mode.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetEqModeRemote(mode.value);
                    this._updateStateFromProxy();
                }
            });
            this.menu.addMenuItem(item);
            this._eqItems.push(item);
        });
        
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 4. Immersive Commute Section
        let commuteTitle = new PopupMenu.PopupMenuItem('Immersive Commute', { reactive: false });
        commuteTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(commuteTitle);

        this._commuteItems = [];
        let commuteModes = [
            { label: 'Off', value: 0 },
            { label: 'Train Sound', value: 1 },
            { label: 'Public Transit', value: 2 },
            { label: 'Airplane Engine', value: 3 }
        ];

        commuteModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('   ' + mode.label);
            item.rawLabel = mode.label;
            item.commuteValue = mode.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetImmersiveCommuteRemote(mode.value);
                    this._updateStateFromProxy();
                }
            });
            this.menu.addMenuItem(item);
            this._commuteItems.push(item);
        });

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 5. Audio Modes & Head Tracking
        let audioTitle = new PopupMenu.PopupMenuItem('Spatial Audio', { reactive: false });
        audioTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(audioTitle);

        this._audioStatusLabel = new St.Label({
            text: 'Current: Off',
            style_class: 'buds-audio-status'
        });
        let audioStatusItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        audioStatusItem.add_child(this._audioStatusLabel);
        this.menu.addMenuItem(audioStatusItem);

        this._audioModeItems = [];
        let audioModes = [
            { label: 'Off (Stereo)', value: 0 },
            { label: 'Dolby Audio', value: 1 },
            { label: 'Xiaomi Immersive Audio', value: 2 }
        ];

        audioModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('   ' + mode.label);
            item.rawLabel = mode.label;
            item.audioValue = mode.value;
            item.connect('activate', () => {
                if (this._proxy) {
                    this._proxy.SetAudioModeRemote(mode.value);
                    this._updateStateFromProxy();
                }
            });
            this.menu.addMenuItem(item);
            this._audioModeItems.push(item);
        });

        this._headToggle = new PopupMenu.PopupSwitchMenuItem('Head Tracking', false);
        this._headToggle.connect('toggled', (item, state) => {
            if (this._proxy) {
                this._proxy.SetHeadTrackingRemote(state);
                this._updateStateFromProxy();
            }
        });
        this.menu.addMenuItem(this._headToggle);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 6. In-Ear Detection (Debounced)
        this._inEarToggle = new PopupMenu.PopupSwitchMenuItem('In-Ear Detection', true);
        this._inEarToggle.connect('toggled', (item, state) => {
            if (this._lockInEar) return;
            this._lockInEar = true;
            if (this._proxy) {
                this._proxy.SetInEarDetectionRemote(state);
            }
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600, () => {
                this._lockInEar = false;
                return GLib.SOURCE_REMOVE;
            });
        });
        this.menu.addMenuItem(this._inEarToggle);
    }

    destroy() {
        if (this._proxy && this._signalId) {
            this._proxy.disconnectSignal(this._signalId);
        }
        super.destroy();
    }
});

export default class BudsExtension extends Extension {
    enable() {
        this._indicator = new BudsIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        try {
            this._settings = this.getSettings();
            Main.wm.addKeybinding(
                'toggle-menu',
                this._settings,
                Meta.KeyBindingFlags.NONE,
                Shell.ActionMode.ALL,
                () => {
                    if (this._indicator) {
                        this._indicator.menu.toggle();
                    }
                }
            );
        } catch (e) {
            console.error('Failed to add keybinding toggle-menu:', e);
        }
    }

    disable() {
        try {
            Main.wm.removeKeybinding('toggle-menu');
        } catch (e) {
            // ignore
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        this._settings = null;
    }
}

