#!/usr/bin/env python3
"""
VirtualBuddy Manager for macOS benchmark testing.

Provides:
- VM lifecycle management (boot, stop, status)
- APFS clone-based snapshot workflow for test isolation
- Window geometry retrieval for coordinate mapping
"""

import subprocess
import urllib.parse
import time
import shutil
import logging
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from Quartz import CGGetActiveDisplayList, CGDisplayBounds

    QUARTZ_DISPLAY_AVAILABLE = True
except Exception:
    QUARTZ_DISPLAY_AVAILABLE = False

logger = logging.getLogger(__name__)


class VirtualBuddyManager:
    provider_name = "virtualbuddy"

    """
    Manager for VirtualBuddy VMs on macOS.
    
    Workflow:
        Clone → Boot → Wait Ready → Execute Test → Stop → Delete Clone
    """
    
    # Default VM library location
    DEFAULT_VM_LIBRARY = Path.home() / "Library" / "Application Support" / "VirtualBuddy"
    
    def __init__(self, vm_library: Optional[Path] = None):
        """
        Initialize the VirtualBuddy manager.
        
        Args:
            vm_library: Path to VirtualBuddy VM library. Defaults to ~/Library/Application Support/VirtualBuddy/
        """
        self.vm_library = Path(vm_library) if vm_library else self.DEFAULT_VM_LIBRARY
        
        if not self.vm_library.exists():
            logger.warning("VM library not found at %s", self.vm_library)

    # =========================================================================
    # VM Lifecycle
    # =========================================================================

    def _vm_bundle_path(self, vm_name: str) -> Path:
        return self.vm_library / f"{vm_name}.vbvm"

    @staticmethod
    def _escape_applescript_string(value: str) -> str:
        """Escape a Python string for use inside AppleScript double quotes."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _send_url_cmd(self, action: str, vm_name: str, args: Optional[Dict[str, str]] = None) -> bool:
        """Send command via VirtualBuddy URL scheme."""
        params = {"name": vm_name}
        if args:
            params.update(args)
        
        query_string = urllib.parse.urlencode(params)
        uri = f"virtualbuddy://{action}?{query_string}"
        
        cmd = f'tell application "System Events" to open location "{uri}"'
        
        try:
            subprocess.run(["osascript", "-e", cmd], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Failed to send %s command: %s", action, e)
            return False

    def boot_vm(self, vm_name: str, recovery_mode: bool = False, 
                wait_for_window: bool = True, timeout: int = 60) -> bool:
        """
        Boot a VirtualBuddy VM.
        
        Args:
            vm_name: Name of the VM to boot.
            recovery_mode: Whether to boot in recovery mode.
            wait_for_window: If True, wait until VM window appears.
            timeout: Maximum time to wait for window (seconds).
            
        Returns:
            True if boot successful, False otherwise.
        """
        # Check if already running
        if self.is_vm_running(vm_name):
            logger.info("VM '%s' is already running.", vm_name)
            self.focus_vm_window(vm_name)
            return True

        logger.info("Booting VM '%s'...", vm_name)
        
        options = {}
        if recovery_mode:
            options["options.bootInRecoveryMode"] = "true"
        
        if self._send_url_cmd("boot", vm_name, options):
            if wait_for_window:
                return self._wait_for_vm_window(vm_name, timeout)
            return True
        return False

    def stop_vm(self, vm_name: str, timeout: int = 30) -> bool:
        """
        Stop a VirtualBuddy VM.
        
        Uses UI scripting to click the Power button in toolbar.
        
        Args:
            vm_name: Name of the VM to stop.
            timeout: Maximum time to wait for VM to stop (seconds).
            
        Returns:
            True if stopped successfully, False otherwise.
        """
        if not self.is_vm_running(vm_name):
            logger.info("VM '%s' is not running.", vm_name)
            return True

        logger.info("Stopping VM '%s'...", vm_name)
        vm_name_escaped = self._escape_applescript_string(vm_name)
        
        # Use UI scripting to click Power button in toolbar
        script = f'''
        tell application "System Events"
            tell process "VirtualBuddy"
                set frontmost to true
                try
                    -- 1. Find the target window
                    if exists window "{vm_name_escaped}" then
                        set targetWindow to window "{vm_name_escaped}"
                    else
                        set targetWindow to first window whose name contains "{vm_name_escaped}"
                    end if
                        
                    -- 2. Click the close button (top-left corner)
                    click (first button whose subrole is "AXCloseButton") of targetWindow
                        
                    -- 3. Wait for the confirmation sheet (poll for up to 2 seconds)
                    set timeoutCounter to 0
                    repeat while not (exists sheet 1 of targetWindow) and timeoutCounter < 20
                        delay 0.1
                        set timeoutCounter to timeoutCounter + 1
                    end repeat
                        
                    -- 4. Click the confirmation button (compatible with English and Chinese)
                    if exists sheet 1 of targetWindow then
                        tell sheet 1 of targetWindow
                            if exists button "Stop VM" then
                                click button "Stop VM"
                            else if exists button "Shut Down" then
                                click button "Shut Down"
                            end if
                        end tell
                    end if
                on error
                    log "Window not found or VM is already stopped"
                end try
            end tell
        end tell
        '''
        try:
            result = self._run_applescript(script).strip()
        except Exception as e:
            logger.error("Stop action failed for '%s': %s", vm_name, e)
            return False
        logger.info("Stop action result: %s", result)
        
        # Wait for window to close
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_vm_running(vm_name):
                logger.info("VM '%s' stopped.", vm_name)
                return True
            time.sleep(1)
        
        logger.warning("Timeout waiting for VM '%s' to stop.", vm_name)
        return False

    def is_vm_running(self, vm_name: str) -> bool:
        """Check if a VM is currently running (window exists)."""
        vm_name_escaped = self._escape_applescript_string(vm_name)
        script = f'''
        tell application "System Events"
            if exists process "VirtualBuddy" then
                tell process "VirtualBuddy"
                    return exists window "{vm_name_escaped}"
                end tell
            else
                return false
            end if
        end tell
        '''
        try:
            result = self._run_applescript(script)
            return result.strip() == "true"
        except Exception:
            return False

    def focus_vm_window(self, vm_name: str) -> bool:
        """Bring VM window to front."""
        vm_name_escaped = self._escape_applescript_string(vm_name)
        script = f'''
        tell application "System Events"
            tell process "VirtualBuddy"
                set frontmost to true
                if exists window "{vm_name_escaped}" then
                    perform action "AXRaise" of window "{vm_name_escaped}"
                    return "true"
                end if
            end tell
        end tell
        return "false"
        '''
        try:
            result = self._run_applescript(script)
            return result.strip() == "true"
        except Exception:
            return False

    def get_vm_window_geometry(self, vm_name: str) -> Optional[Dict[str, int]]:
        """
        Get VM window position and size.
        
        Returns:
            Dictionary with x, y, width, height, or None if not found.
        """
        vm_name_escaped = self._escape_applescript_string(vm_name)
        script = f'''
        tell application "System Events"
            if exists process "VirtualBuddy" then
                tell process "VirtualBuddy"
                    if exists window "{vm_name_escaped}" then
                        set p to position of window "{vm_name_escaped}"
                        set s to size of window "{vm_name_escaped}"
                        return {{p, s}}
                    end if
                end tell
            end if
        end tell
        '''
        try:
            result = self._run_applescript(script)
            if not result.strip():
                return None
            
            # Parse "x, y, width, height" format
            parts = [x.strip() for x in result.strip().split(',')]
            if len(parts) >= 4:
                return {
                    "x": int(parts[0]),
                    "y": int(parts[1]),
                    "width": int(parts[2]),
                    "height": int(parts[3])
                }
            return None
        except Exception as e:
            logger.warning("Error getting geometry for '%s': %s", vm_name, e)
            return None

    def set_vm_window_geometry(
        self, vm_name: str, x: int, y: int, width: int, height: int
    ) -> bool:
        """Set VM window position and size."""
        vm_name_escaped = self._escape_applescript_string(vm_name)
        script = f'''
        tell application "System Events"
            if exists process "VirtualBuddy" then
                tell process "VirtualBuddy"
                    set frontmost to true
                    if exists window "{vm_name_escaped}" then
                        set targetWindow to window "{vm_name_escaped}"
                        set position of targetWindow to {{{int(x)}, {int(y)}}}
                        set size of targetWindow to {{{int(width)}, {int(height)}}}
                        return "true"
                    end if
                end tell
            end if
        end tell
        return "false"
        '''
        try:
            result = self._run_applescript(script)
            return result.strip() == "true"
        except Exception as e:
            logger.warning("Error setting geometry for '%s': %s", vm_name, e)
            return False

    def fit_vm_window_to_main_screen(self, vm_name: str, margin: int = 0) -> bool:
        """
        Fit VM window to the display that currently contains this VM window.
        """
        window_geo = self.get_vm_window_geometry(vm_name)
        if not window_geo:
            return False

        # Select the desktop bounds that contain the current window center.
        desktops = self._get_all_desktop_bounds()
        if not desktops:
            # Fallback: keep the window anchored on current display (do not move),
            # only enlarge size to avoid cross-display jumps when display bounds
            # cannot be enumerated.
            return self.set_vm_window_geometry(
                vm_name,
                int(window_geo["x"]),
                int(window_geo["y"]),
                int(max(1200, window_geo["width"])),
                int(max(800, window_geo["height"])),
            )

        cx = int(window_geo["x"] + window_geo["width"] / 2)
        cy = int(window_geo["y"] + window_geo["height"] / 2)
        target = None
        for left, top, right, bottom in desktops:
            if left <= cx <= right and top <= cy <= bottom:
                target = (left, top, right, bottom)
                break

        # Fallback to first desktop if center cannot be matched.
        if target is None:
            target = desktops[0]

        left, top, right, bottom = target
        screen_width = max(0, right - left)
        screen_height = max(0, bottom - top)

        safe_margin = max(0, int(margin))
        x = int(left + safe_margin)
        y = int(top + safe_margin)
        width = int(max(640, screen_width - 2 * safe_margin))
        height = int(max(480, screen_height - 2 * safe_margin))
        return self.set_vm_window_geometry(vm_name, x, y, width, height)

    def _get_all_desktop_bounds(self) -> List[Tuple[int, int, int, int]]:
        """Return bounds for each desktop/display as (left, top, right, bottom)."""
        if QUARTZ_DISPLAY_AVAILABLE:
            try:
                err, displays, count = CGGetActiveDisplayList(16, None, None)
                if int(err) != 0:
                    return []
                ids = list(displays or [])
                if count:
                    ids = ids[: int(count)]
                bounds: List[Tuple[int, int, int, int]] = []
                for display_id in ids:
                    rect = CGDisplayBounds(display_id)
                    left = int(rect.origin.x)
                    top = int(rect.origin.y)
                    right = int(rect.origin.x + rect.size.width)
                    bottom = int(rect.origin.y + rect.size.height)
                    if right > left and bottom > top:
                        bounds.append((left, top, right, bottom))
                return bounds
            except Exception as e:
                logger.warning("Error reading display bounds via Quartz: %s", e)

        script = 'tell application "Finder" to get bounds of window of desktop'
        try:
            raw = self._run_applescript(script).strip()
            nums = [int(float(v)) for v in re.findall(r"-?\d+(?:\.\d+)?", raw)]
            if len(nums) < 4:
                return []
            bounds: List[Tuple[int, int, int, int]] = []
            for i in range(0, len(nums) - 3, 4):
                left, top, right, bottom = nums[i:i + 4]
                bounds.append((left, top, right, bottom))
            return bounds
        except Exception as e:
            logger.warning("Error reading desktop bounds: %s", e)
            return []

    def _wait_for_vm_window(self, vm_name: str, timeout: int) -> bool:
        """Wait for VM window to appear."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_vm_running(vm_name):
                logger.info("VM '%s' window detected.", vm_name)
                return True
            time.sleep(1)
        logger.warning("Timeout waiting for VM '%s' window.", vm_name)
        return False

    def _run_applescript(self, script: str) -> str:
        """Run AppleScript and return stdout."""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            raise RuntimeError(f"osascript failed (code={result.returncode}): {detail}")
        return result.stdout

    # =========================================================================
    # VM Library and Clone Ops
    # =========================================================================

    def list_vms(self) -> List[str]:
        """List available VMs in the library."""
        if not self.vm_library.exists():
            return []
        return sorted(
            item.stem
            for item in self.vm_library.iterdir()
            if item.suffix == ".vbvm" and item.is_dir()
        )

    def vm_exists(self, vm_name: str) -> bool:
        """Check if a VM bundle exists in the library."""
        return self._vm_bundle_path(vm_name).exists()

    def ensure_vm_stopped(self, vm_name: str, timeout: int = 30) -> bool:
        """Ensure VM is stopped; if running, attempt graceful stop."""
        if not self.is_vm_running(vm_name):
            return True
        logger.info("VM '%s' is running, attempting stop before clone...", vm_name)
        return self.stop_vm(vm_name, timeout=timeout)

    def resolve_runtime_host(self, vm_name: str, fallback_host: str | None = None) -> str:
        """VirtualBuddy clone flow relies on the configured runtime host."""
        host = str(fallback_host or "").strip()
        if not host:
            raise RuntimeError(f"No runtime host configured for VirtualBuddy VM '{vm_name}'")
        return host

    def clone_vm(
        self,
        source_name: str,
        clone_name: str,
    ) -> bool:
        """
        Create an APFS clone of a VM.
        
        Uses `cp -c` for instant, space-efficient cloning.
        
        Args:
            source_name: Name of the source VM.
            clone_name: Name for the cloned VM.
            
        Returns:
            True if clone created successfully, False otherwise.
        """
        source_path = self._vm_bundle_path(source_name)
        clone_path = self._vm_bundle_path(clone_name)
        
        if not source_path.exists():
            logger.error("Source VM '%s' not found.", source_name)
            return False
        
        if clone_path.exists():
            logger.error("Clone '%s' already exists.", clone_name)
            return False

        if self.is_vm_running(source_name):
            logger.error(
                "Source VM '%s' is running. Please stop it before cloning.",
                source_name,
            )
            return False
        
        logger.info("Cloning '%s' -> '%s'...", source_name, clone_name)
        
        try:
            # Use cp -c for APFS clone (copy-on-write)
            subprocess.run(
                ["cp", "-c", "-R", str(source_path), str(clone_path)],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info("Clone created: %s", clone_path)
            time.sleep(1)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Clone failed: %s", (e.stderr or "").strip())
            return False

    def delete_clone(self, clone_name: str) -> bool:
        """
        Delete a cloned VM.
        
        Args:
            clone_name: Name of the VM to delete.
            
        Returns:
            True if deleted successfully, False otherwise.
        """
        clone_path = self._vm_bundle_path(clone_name)
        
        if not clone_path.exists():
            logger.info("VM '%s' not found.", clone_name)
            return True  # Already doesn't exist
        
        # Safety check: Don't delete if VM is running
        if self.is_vm_running(clone_name):
            logger.warning("Cannot delete '%s': VM is still running.", clone_name)
            return False
        
        logger.info("Deleting '%s'...", clone_name)
        
        try:
            shutil.rmtree(clone_path)
            logger.info("Deleted: %s", clone_path)
            return True
        except Exception as e:
            logger.error("Delete failed for '%s': %s", clone_name, e)
            return False

    # =========================================================================
    # Benchmark Environment Workflow
    # =========================================================================

    def prepare_benchmark_environment(
        self,
        base_vm_name: str,
        clone_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Prepare a fresh benchmark environment by cloning the base VM.
        
        Args:
            base_vm_name: Name of the base VM to clone.
            clone_name: Explicit clone VM name. When omitted, a timestamp name is generated.
            
        Returns:
            Clone VM name if successful, None if failed.
        """
        if not self.ensure_vm_stopped(base_vm_name, timeout=60):
            logger.error("Base VM '%s' must be stopped before clone.", base_vm_name)
            return None

        resolved_clone_name = (clone_name or "").strip() or f"{base_vm_name}_{int(time.time() * 1000)}"
        
        # Create clone
        if not self.clone_vm(base_vm_name, resolved_clone_name):
            return None
        
        # Boot the clone
        if not self.boot_vm(resolved_clone_name, wait_for_window=True, timeout=90):
            # Cleanup on failure (VM may still be running if window detection times out).
            self.cleanup_benchmark_environment(resolved_clone_name)
            return None

        if not self.fit_vm_window_to_main_screen(resolved_clone_name):
            logger.warning("Failed to fit VM window for '%s'", resolved_clone_name)
        
        return resolved_clone_name

    def cleanup_benchmark_environment(self, clone_name: str) -> bool:
        """
        Cleanup benchmark environment by stopping and deleting the clone.
        
        Args:
            clone_name: Name of the cloned VM to cleanup.
            
        Returns:
            True if cleanup successful, False otherwise.
        """
        # Stop VM if running
        if self.is_vm_running(clone_name):
            if not self.stop_vm(clone_name, timeout=30):
                logger.warning("Could not stop '%s'", clone_name)
                return False
        
        # Delete clone
        return self.delete_clone(clone_name)


if __name__ == "__main__":
    # Quick smoke test
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    controller = VirtualBuddyManager()
    logger.info("Available VMs: %s", controller.list_vms())
