/** OnePlus 9R bring-up: run the embedded probe before attempting any OS boot.
    SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Pi/PiFirmwareFile.h>
#include <Library/BaseLib.h>
#include <Library/DxeServicesLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PlatformBootManagerLib.h>
#include <Library/UefiBootManagerLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>

// Matches the FILE APPLICATION in the generated lemonades.fdf.
STATIC EFI_GUID mProbeGuid = {
  0xd87a6391, 0x9637, 0x493a, {0xb6, 0x40, 0x3c, 0xb8, 0xac, 0x57, 0x36, 0x99}
};

VOID EFIAPI PlatformBootManagerBeforeConsole (VOID)
{
  EfiBootManagerConnectAll ();
}

VOID EFIAPI PlatformBootManagerAfterConsole (VOID)
{
  EFI_STATUS Status;
  EFI_HANDLE Image = NULL;
  VOID      *Buffer = NULL;
  UINTN      Size = 0;

  Print (L"OnePlus 9R: experimental UEFI probe; not an iOS ROM.\r\n");
  Status = GetSectionFromAnyFv (&mProbeGuid, EFI_SECTION_PE32, 0, &Buffer, &Size);
  if (!EFI_ERROR (Status)) {
    Status = gBS->LoadImage (FALSE, gImageHandle, NULL, Buffer, Size, &Image);
    FreePool (Buffer);
  }
  if (!EFI_ERROR (Status)) {
    Status = gBS->StartImage (Image, NULL, NULL);
  }
  Print (L"Probe returned: %r. Hold power to restart.\r\n", Status);
  // No fallback to a disk boot, secure-boot enrolment or persistent boot options.
  CpuDeadLoop ();
}

VOID EFIAPI PlatformBootManagerOnDemandConInConnect (VOID) {}
VOID EFIAPI PlatformBootManagerProcessBootCompletion (OUT EFI_BOOT_MANAGER_LOAD_OPTION *BootOption) {}
VOID EFIAPI PlatformBootManagerPriorityBoot (IN OUT UINT16 **BootNext) {}
VOID EFIAPI PlatformBootManagerWaitCallback (IN UINT16 TimeoutRemain) {}
VOID EFIAPI PlatformBootManagerUnableToBoot (VOID) { CpuDeadLoop (); }
VOID EFIAPI PlatformBootManagerBdsEntry (VOID) {}
