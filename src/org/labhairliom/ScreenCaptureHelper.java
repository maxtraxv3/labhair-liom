package org.labhairliom;

import android.hardware.display.VirtualDisplay;
import android.media.projection.MediaProjection;
import android.view.Surface;

public class ScreenCaptureHelper {
    public static VirtualDisplay createDisplay(
            MediaProjection projection,
            String name, int width, int height, int dpi,
            Surface surface, int flags) {
        return projection.createVirtualDisplay(
            name, width, height, dpi, flags, surface, null, null);
    }
}
