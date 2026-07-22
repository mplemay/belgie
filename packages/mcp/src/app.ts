import type { App } from "@modelcontextprotocol/ext-apps";

import { closeModal as closeModalImpl, openModal } from "./modal";
import type { ModalOptions } from "./modal";
import { getActiveWidget } from "./widget-context";

export function sendMessage(...args: Parameters<App["sendMessage"]>): ReturnType<App["sendMessage"]> {
  return getActiveWidget().sendMessage(...args);
}

export function sendLog(...args: Parameters<App["sendLog"]>): ReturnType<App["sendLog"]> {
  return getActiveWidget().sendLog(...args);
}

export function updateModelContext(
  ...args: Parameters<App["updateModelContext"]>
): ReturnType<App["updateModelContext"]> {
  return getActiveWidget().updateModelContext(...args);
}

export function openLink(...args: Parameters<App["openLink"]>): ReturnType<App["openLink"]> {
  return getActiveWidget().openLink(...args);
}

export function downloadFile(...args: Parameters<App["downloadFile"]>): ReturnType<App["downloadFile"]> {
  return getActiveWidget().downloadFile(...args);
}

export function requestDisplayMode(
  ...args: Parameters<App["requestDisplayMode"]>
): ReturnType<App["requestDisplayMode"]> {
  return getActiveWidget().requestDisplayMode(...args);
}

export function requestTeardown(...args: Parameters<App["requestTeardown"]>): ReturnType<App["requestTeardown"]> {
  return getActiveWidget().requestTeardown(...args);
}

export function requestModal(options: ModalOptions): void {
  getActiveWidget();
  openModal(options);
}

export function closeModal(): void {
  getActiveWidget();
  closeModalImpl();
}
