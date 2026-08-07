import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';

const DBUS_SERVICE = 'org.redmibuds8.Control';
const DBUS_PATH = '/org/redmibuds8/Control';

const DBusProxy = Gio.DBusProxy.makeProxyWrapper(`
<node>
    <interface name="org.redmibuds8.Control">
        <method name="SetAncMode">
            <arg type="i" name="mode" direction="in"/>
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
        <method name="SetHeadTracking">
            <arg type="b" name="enabled" direction="in"/>
        </method>
        <method name="SetAudioMode">
            <arg type="b" name="dolby" direction="in"/>
        </method>
        <property name="Connected" type="b" access="read"/>
    </interface>
</node>
`);

const BudsIndicator = GObject.registerClass(
class BudsIndicator extends PanelMenu.Button {
    constructor() {
        super(0.0, 'Redmi Buds 8 Pro');
        
        let icon = new St.Icon({
            icon_name: 'audio-headphones-symbolic',
            style_class: 'system-status-icon'
        });
        this.add_child(icon);

        this._proxy = null;
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
        } catch (e) {
            console.error('Failed to connect to Redmi Buds daemon:', e);
        }
    }

    _buildMenu() {
        // ANC Section
        let ancTitle = new PopupMenu.PopupMenuItem('Noise Cancellation', { reactive: false });
        ancTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(ancTitle);

        let ancModes = [
            { label: 'Off', value: 0 },
            { label: 'ANC On', value: 1 },
            { label: 'Transparency', value: 2 }
        ];

        ancModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('  ' + mode.label);
            item.connect('activate', () => {
                if (this._proxy) this._proxy.SetAncModeRemote(mode.value);
            });
            this.menu.addMenuItem(item);
        });

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // EQ Section
        let eqTitle = new PopupMenu.PopupMenuItem('Equalizer', { reactive: false });
        eqTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(eqTitle);

        let eqModes = [
            { label: 'Standard', value: 1 },
            { label: 'Music', value: 2 },
            { label: 'Video', value: 3 },
            { label: 'Game', value: 4 },
            { label: 'Audio Books', value: 5 }
        ];

        eqModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('  ' + mode.label);
            item.connect('activate', () => {
                if (this._proxy) this._proxy.SetEqModeRemote(mode.value);
            });
            this.menu.addMenuItem(item);
        });
        
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Immersive Commute
        let commuteTitle = new PopupMenu.PopupMenuItem('Immersive Commute', { reactive: false });
        commuteTitle.label.add_style_class_name('buds-menu-title');
        this.menu.addMenuItem(commuteTitle);

        let commuteModes = [
            { label: 'Off', value: 0 },
            { label: 'Train', value: 1 },
            { label: 'Public Transit', value: 2 },
            { label: 'Airplane', value: 3 }
        ];

        commuteModes.forEach(mode => {
            let item = new PopupMenu.PopupMenuItem('  ' + mode.label);
            item.connect('activate', () => {
                if (this._proxy) this._proxy.SetImmersiveCommuteRemote(mode.value);
            });
            this.menu.addMenuItem(item);
        });

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        
        // Toggles
        let inEarToggle = new PopupMenu.PopupSwitchMenuItem('In-Ear Detection', true);
        inEarToggle.connect('toggled', (item, state) => {
            if (this._proxy) this._proxy.SetInEarDetectionRemote(state);
        });
        this.menu.addMenuItem(inEarToggle);

        let headToggle = new PopupMenu.PopupSwitchMenuItem('Head Tracking', false);
        headToggle.connect('toggled', (item, state) => {
            if (this._proxy) this._proxy.SetHeadTrackingRemote(state);
        });
        this.menu.addMenuItem(headToggle);
        
        let audioToggle = new PopupMenu.PopupSwitchMenuItem('Dolby Audio (vs Dimensional)', true);
        audioToggle.connect('toggled', (item, state) => {
            if (this._proxy) this._proxy.SetAudioModeRemote(state);
        });
        this.menu.addMenuItem(audioToggle);
    }
});

export default class BudsExtension extends Extension {
    enable() {
        this._indicator = new BudsIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
