<script setup lang="ts">
import { useVirtualizer } from "@tanstack/vue-virtual";
import { storeToRefs } from "pinia";
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  nextTick,
  useTemplateRef,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import useFavoriteToggle from "@/composables/useFavoriteToggle";
import BackButton from "@/console/components/BackButton.vue";
import GameCard from "@/console/components/GameCard.vue";
import NavigationHint from "@/console/components/NavigationHint.vue";
import useBackgroundArt from "@/console/composables/useBackgroundArt";
import { gamesListElementRegistry } from "@/console/composables/useElementRegistry";
import { useInputScope } from "@/console/composables/useInputScope";
import { useSpatialNav } from "@/console/composables/useSpatialNav";
import type { InputAction } from "@/console/input/actions";
import { ROUTES } from "@/plugins/router";
import storeCollections from "@/stores/collections";
import storeConsole from "@/stores/console";
import storeGalleryFilter from "@/stores/galleryFilter";
import storePlatforms from "@/stores/platforms";
import storeRoms, { type SimpleRom } from "@/stores/roms";

const route = useRoute();
const router = useRouter();
const consoleStore = storeConsole();
const galleryFilterStore = storeGalleryFilter();
const platformsStore = storePlatforms();
const { allPlatforms } = storeToRefs(platformsStore);
const collectionsStore = storeCollections();
const { allCollections, smartCollections, virtualCollections } =
  storeToRefs(collectionsStore);
const romsStore = storeRoms();
const {
  filteredRoms,
  fetchingRoms,
  currentPlatform,
  currentCollection,
  currentSmartCollection,
  currentVirtualCollection,
} = storeToRefs(romsStore);
const { toggleFavorite: toggleFavoriteComposable } = useFavoriteToggle();
const { setSelectedBackgroundArt, clearSelectedBackgroundArt } =
  useBackgroundArt();

const isPlatformRoute = route.name === ROUTES.CONSOLE_PLATFORM;
const isCollectionRoute = route.name === ROUTES.CONSOLE_COLLECTION;
const isSmartCollectionRoute = route.name === ROUTES.CONSOLE_SMART_COLLECTION;
const isVirtualCollectionRoute =
  route.name === ROUTES.CONSOLE_VIRTUAL_COLLECTION;

const selectedIndex = ref(0);
const loadedMap = ref<Record<number, boolean>>({});
const inAlphabet = ref(false);
const alphaIndex = ref(0);

// --- Virtual scrolling setup ---
const scrollContainerRef = useTemplateRef<HTMLDivElement>("scroll-container-ref");
const gridMeasureRef = useTemplateRef<HTMLDivElement>("grid-measure-ref");

// Card dimensions (matching CSS: minmax(250px,250px) card + gap-5 = 20px)
const CARD_WIDTH = 250;
const GAP = 20;
const ROW_HEIGHT = 370 + GAP; // card height (~350px content + border) + gap

// Dynamic column count based on container width
const columnCount = ref(4);

function updateColumnCount() {
  if (!gridMeasureRef.value) return;
  const containerWidth = gridMeasureRef.value.clientWidth;
  if (containerWidth <= 0) return;
  // Match CSS: repeat(auto-fill, minmax(250px, 250px))
  // Available width for cards = containerWidth
  // Each card takes CARD_WIDTH, plus gaps between them
  const cols = Math.max(1, Math.floor((containerWidth + GAP) / (CARD_WIDTH + GAP)));
  columnCount.value = cols;
}

// ResizeObserver for responsive column count
let resizeObserver: ResizeObserver | null = null;

// Row count for virtualizer
const rowCount = computed(() =>
  Math.ceil(filteredRoms.value.length / columnCount.value),
);

// Group roms into rows
function getRowItems(rowIndex: number): { rom: SimpleRom; flatIndex: number }[] {
  const cols = columnCount.value;
  const start = rowIndex * cols;
  const end = Math.min(start + cols, filteredRoms.value.length);
  const items: { rom: SimpleRom; flatIndex: number }[] = [];
  for (let i = start; i < end; i++) {
    items.push({ rom: filteredRoms.value[i], flatIndex: i });
  }
  return items;
}

// Virtualizer instance
const virtualizer = useVirtualizer(
  computed(() => ({
    count: rowCount.value,
    getScrollElement: () => scrollContainerRef.value ?? null,
    estimateSize: () => ROW_HEIGHT,
    overscan: 3,
  })),
);

// Helper: get column count for spatial nav (getCols)
function getCols(): number {
  return columnCount.value;
}

// --- Scroll-to-row + focus logic ---
// When selectedIndex changes, ensure the target row is visible and focused.
// This replaces useRovingDom for the virtual scroll case.
function rowForIndex(idx: number): number {
  return Math.floor(idx / columnCount.value);
}

/**
 * Scroll to make the row containing `idx` visible, then focus the element.
 * If `instant` is true, use instant scroll (for initial load). Otherwise smooth.
 */
async function scrollToAndFocus(idx: number, behavior: ScrollBehavior = "smooth") {
  const row = rowForIndex(idx);

  // Tell virtualizer to scroll to this row
  virtualizer.value.scrollToIndex(row, { align: "center", behavior });

  // Wait for the DOM to render the target row
  await nextTick();
  // Additional frame wait for virtualizer to process scroll
  await new Promise((r) => requestAnimationFrame(r));
  await nextTick();

  const el = gamesListElementRegistry.getElement(idx);
  if (el) {
    el.setAttribute("tabindex", "0");
    el.focus({ preventScroll: true });
  } else {
    // Element not yet rendered — retry once after another frame
    await new Promise((r) => requestAnimationFrame(r));
    await nextTick();
    const el2 = gamesListElementRegistry.getElement(idx);
    if (el2) {
      el2.setAttribute("tabindex", "0");
      el2.focus({ preventScroll: true });
    }
  }
}

// Watch selectedIndex to handle scroll + focus
watch(selectedIndex, (newIdx, oldIdx) => {
  // Remove tabindex from old element if available
  if (oldIdx != null) {
    const prev = gamesListElementRegistry.getElement(oldIdx);
    if (prev) prev.setAttribute("tabindex", "-1");
  }

  // Check if element is already rendered (same virtual window)
  const el = gamesListElementRegistry.getElement(newIdx);
  if (el) {
    el.setAttribute("tabindex", "0");
    el.focus({ preventScroll: true });
    // Still scroll to keep it centered
    el.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
  } else {
    // Element not in DOM — need to scroll virtualizer first
    scrollToAndFocus(newIdx);
  }
});

// Generate alphabet letters dynamically based on available games
const letters = computed(() => {
  const letterSet = new Set<string>();

  filteredRoms.value.forEach(({ name }) => {
    if (!name) return;

    const normalized = normalizeTitle(name);
    const firstChar = normalized.charAt(0).toUpperCase();

    if (/[A-Z]/.test(firstChar)) {
      letterSet.add(firstChar);
    } else if (/[0-9]/.test(firstChar)) {
      letterSet.add("#");
    }
  });

  const result = Array.from(letterSet).sort();
  // Move # to the beginning if it exists
  const hashIndex = result.indexOf("#");
  if (hashIndex > -1) {
    result.splice(hashIndex, 1);
    result.unshift("#");
  }

  return result;
});

function persistIndex() {
  if (currentPlatform.value != null) {
    consoleStore.setPlatformGameIndex(
      currentPlatform.value.id,
      selectedIndex.value,
    );
  } else if (currentCollection.value != null) {
    consoleStore.setCollectionGameIndex(
      currentCollection.value.id,
      selectedIndex.value,
    );
  } else if (currentSmartCollection.value != null) {
    consoleStore.setSmartCollectionGameIndex(
      currentSmartCollection.value.id,
      selectedIndex.value,
    );
  } else if (currentVirtualCollection.value != null) {
    consoleStore.setVirtualCollectionGameIndex(
      currentVirtualCollection.value.id,
      selectedIndex.value,
    );
  }
}

function navigateBack() {
  persistIndex();
  router.push({ name: ROUTES.CONSOLE_HOME });
}

const headerTitle = computed(() => {
  if (isCollectionRoute) {
    return currentCollection.value?.name || "Collection";
  }
  if (isSmartCollectionRoute) {
    return currentSmartCollection.value?.name || "Smart Collection";
  }
  if (isVirtualCollectionRoute) {
    return currentVirtualCollection.value?.name || "Virtual Collection";
  }

  return (
    currentPlatform.value?.display_name ||
    currentPlatform.value?.slug.toUpperCase()
  );
});

const { subscribe } = useInputScope();
const {
  moveLeft,
  moveRight,
  moveUp,
  moveDown: moveDownBasic,
} = useSpatialNav(selectedIndex, getCols, () => filteredRoms.value.length);

function handleAction(action: InputAction): boolean {
  if (!filteredRoms.value.length) return false;
  if (inAlphabet.value) {
    if (action === "moveLeft") {
      inAlphabet.value = false;
      return true;
    }
    if (action === "moveUp") {
      alphaIndex.value = Math.max(0, alphaIndex.value - 1);
      return true;
    }
    if (action === "moveDown") {
      alphaIndex.value = Math.min(
        Array.from(letters.value).length - 1,
        alphaIndex.value + 1,
      );
      return true;
    }
    if (action === "confirm") {
      const L = Array.from(letters.value)[alphaIndex.value];
      const idx = filteredRoms.value.findIndex((r) => {
        const normalized = normalizeTitle(r.name || "");
        if (L === "#") {
          return /^[0-9]/.test(normalized);
        }
        return normalized.startsWith(L);
      });
      if (idx >= 0) {
        selectedIndex.value = idx;
        // scrollToAndFocus is triggered by the watch on selectedIndex
      }
      return true;
    }
    if (action === "back") {
      inAlphabet.value = false;
      return true;
    }
    return true;
  }
  switch (action) {
    case "moveRight": {
      const before = selectedIndex.value;
      moveRight();
      if (selectedIndex.value === before) {
        inAlphabet.value = true;
        alphaIndex.value = 0;
      }
      return true;
    }
    case "moveLeft":
      moveLeft();
      return true;
    case "moveUp":
      moveUp();
      return true;
    case "moveDown": {
      const before = selectedIndex.value;
      moveDownBasic();
      if (selectedIndex.value === before) {
        const cols = getCols();
        const count = filteredRoms.value.length;
        const totalRows = Math.ceil(count / cols);
        const currentRow = Math.floor(before / cols);
        if (totalRows > currentRow + 1) {
          selectedIndex.value = count - 1;
        }
      }
      return true;
    }
    case "back":
      navigateBack();
      return true;
    case "confirm": {
      selectAndOpen(
        selectedIndex.value,
        filteredRoms.value[selectedIndex.value],
      );
      return true;
    }
    case "toggleFavorite": {
      const rom = filteredRoms.value[selectedIndex.value];
      if (rom) toggleFavoriteComposable(rom);
      return true;
    }
    default:
      return false;
  }
}

function mouseSelect(i: number) {
  selectedIndex.value = i;
}

function selectAndOpen(i: number, rom: SimpleRom) {
  selectedIndex.value = i;
  // Don't navigate if we're in alphabet mode
  if (inAlphabet.value) return;

  persistIndex();

  const query: Record<string, number | string> = {};
  if (isPlatformRoute && currentPlatform.value != null)
    query.id = currentPlatform.value.id;
  if (isCollectionRoute && currentCollection.value != null)
    query.collection = currentCollection.value.id;
  if (isSmartCollectionRoute && currentSmartCollection.value != null)
    query.smartCollection = currentSmartCollection.value.id;
  if (isVirtualCollectionRoute && currentVirtualCollection.value != null)
    query.virtualCollection = currentVirtualCollection.value.id;

  router.push({
    name: ROUTES.CONSOLE_ROM,
    params: { rom: rom.id },
    query: Object.keys(query).length ? query : undefined,
  });
}

function jumpToLetter(L: string) {
  const idx = filteredRoms.value.findIndex((r) => {
    const normalized = normalizeTitle(r.name || "");
    if (L === "#") {
      return /^[0-9]/.test(normalized);
    }
    return normalized.startsWith(L);
  });

  if (idx >= 0) {
    selectedIndex.value = idx;
    inAlphabet.value = false;
  }
}

function normalizeTitle(name: string) {
  return name.toUpperCase().replace(/^(THE|A|AN)\s+/, "");
}

let off: (() => void) | null = null;

function resetGallery() {
  romsStore.reset();
  galleryFilterStore.resetFilters();
  galleryFilterStore.activeFilterDrawer = false;
}

async function fetchRoms() {
  romsStore.setLimit(2000);
  romsStore.setOrderBy("name");
  romsStore.setOrderDir("asc");
  romsStore.resetPagination();

  const fetchedRoms = await romsStore.fetchRoms(false);

  if (selectedIndex.value >= fetchedRoms.length) selectedIndex.value = 0;
  await nextTick();

  // After roms load, scroll to the restored selectedIndex
  scrollToAndFocus(selectedIndex.value, "instant");
}

onMounted(async () => {
  // Setup ResizeObserver for dynamic column count
  if (gridMeasureRef.value) {
    updateColumnCount();
    resizeObserver = new ResizeObserver(() => {
      updateColumnCount();
    });
    resizeObserver.observe(gridMeasureRef.value);
  }

  const routePlatformId = isPlatformRoute ? Number(route.params.id) : null;
  const routeCollectionId = isCollectionRoute ? Number(route.params.id) : null;
  const routeSmartCollectionId = isSmartCollectionRoute
    ? Number(route.params.id)
    : null;
  const routeVirtualCollectionId = isVirtualCollectionRoute
    ? String(route.params.id)
    : null;

  watch(
    () => allPlatforms.value,
    async (platforms) => {
      if (platforms.length > 0) {
        const platform = platforms.find(
          (platform) => platform.id === routePlatformId,
        );

        if (!platform) return;
        // Check if the current platform is different or no ROMs have been loaded
        if (
          currentPlatform.value?.id !== routePlatformId ||
          filteredRoms.value.length === 0
        ) {
          resetGallery();
          romsStore.setCurrentPlatform(platform);
          selectedIndex.value = consoleStore.getPlatformGameIndex(platform.id);
          document.title = platform.display_name;
          await fetchRoms();
        }
      }
    },
    { immediate: true },
  );

  watch(
    () => allCollections.value,
    async (collections) => {
      if (collections.length > 0) {
        const collection = collections.find(
          (collection) => collection.id === routeCollectionId,
        );

        if (!collection) return;
        if (
          currentCollection.value?.id !== routeCollectionId ||
          filteredRoms.value.length === 0
        ) {
          resetGallery();
          romsStore.setCurrentCollection(collection);
          selectedIndex.value = consoleStore.getCollectionGameIndex(
            collection.id,
          );
          document.title = collection.name;
          await fetchRoms();
        }
      }
    },
    { immediate: true },
  );

  watch(
    () => smartCollections.value,
    async (smartCollections) => {
      if (smartCollections.length > 0) {
        const smartCollection = smartCollections.find(
          (smartCollection) => smartCollection.id === routeSmartCollectionId,
        );

        if (!smartCollection) return;
        if (
          currentSmartCollection.value?.id !== routeSmartCollectionId ||
          filteredRoms.value.length === 0
        ) {
          resetGallery();
          romsStore.setCurrentSmartCollection(smartCollection);
          selectedIndex.value = consoleStore.getSmartCollectionGameIndex(
            smartCollection.id,
          );
          document.title = smartCollection.name;
          await fetchRoms();
        }
      }
    },
    { immediate: true },
  );

  watch(
    () => virtualCollections.value,
    async (virtualCollections) => {
      if (virtualCollections.length > 0) {
        const virtualCollection = virtualCollections.find(
          (virtualCollection) =>
            virtualCollection.id === routeVirtualCollectionId,
        );

        if (!virtualCollection) return;
        if (
          currentVirtualCollection.value?.id !== routeVirtualCollectionId ||
          filteredRoms.value.length === 0
        ) {
          resetGallery();
          romsStore.setCurrentVirtualCollection(virtualCollection);
          selectedIndex.value = consoleStore.getVirtualCollectionGameIndex(
            virtualCollection.id,
          );
          document.title = virtualCollection.name;
          await fetchRoms();
        }
      }
    },
    { immediate: true },
  );

  off = subscribe(handleAction);
});

onUnmounted(() => {
  off?.();
  off = null;
  persistIndex();
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});

function markLoaded(id: number) {
  loadedMap.value[id] = true;
}

function handleItemSelected(coverUrl: string) {
  setSelectedBackgroundArt(coverUrl);
}

function handleItemDeselected() {
  clearSelectedBackgroundArt();
}
</script>

<template>
  <div
    ref="scroll-container-ref"
    class="relative min-h-screen overflow-y-auto overflow-x-hidden max-w-[100vw] flex"
    @wheel.prevent
  >
    <BackButton :text="headerTitle" :on-back="navigateBack" />
    <div
      class="relative flex-1 min-w-0 pr-[40px]"
      :style="{ width: 'calc(100vw - 40px)' }"
    >
      <div
        v-if="fetchingRoms"
        class="text-center mt-8"
        :style="{ color: 'var(--console-loading-text)' }"
      >
        Loading games...
      </div>
      <div v-else>
        <div
          v-if="filteredRoms.length === 0"
          class="text-center text-fgDim p-4"
        >
          No games found.
        </div>
        <div
          v-else
          ref="grid-measure-ref"
          class="my-12 px-13 md:px-16 lg:px-20 xl:px-28 py-8 relative z-10 w-full box-border overflow-x-hidden"
        >
          <!-- Virtualizer total height container -->
          <div
            :style="{
              height: `${virtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }"
          >
            <!-- Each virtual row -->
            <div
              v-for="virtualRow in virtualizer.getVirtualItems()"
              :key="virtualRow.key as PropertyKey"
              :style="{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }"
            >
              <div
                class="grid grid-cols-[repeat(auto-fill,minmax(250px,250px))] justify-center gap-5 w-full"
              >
                <GameCard
                  v-for="item in getRowItems(virtualRow.index)"
                  :key="item.rom.id"
                  :rom="item.rom"
                  :index="item.flatIndex"
                  :selected="!inAlphabet && item.flatIndex === selectedIndex"
                  :loaded="!!loadedMap[item.rom.id]"
                  registry="gamesList"
                  @click="selectAndOpen(item.flatIndex, item.rom)"
                  @focus="mouseSelect(item.flatIndex)"
                  @loaded="markLoaded(item.rom.id)"
                  @select="handleItemSelected"
                  @deselect="handleItemDeselected"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div
      class="w-[40px] backdrop-blur fixed top-0 right-0 h-screen overflow-hidden z-30 flex-shrink-0"
      :style="{
        backgroundColor: 'var(--console-gameslist-scrollbar-bg)',
      }"
    >
      <div class="flex flex-col h-screen pa-2 items-center justify-evenly">
        <button
          v-for="(L, i) in letters"
          :key="L"
          class="rounded w-7 h-7 text-[0.7rem] font-semibold flex items-center justify-center shrink-0 transition-all border"
          :style="{
            backgroundColor:
              inAlphabet && i === alphaIndex
                ? 'var(--console-gameslist-alphabet-active-bg)'
                : 'var(--console-gameslist-alphabet-bg)',
            borderColor: 'var(--console-gameslist-alphabet-border)',
            color:
              inAlphabet && i === alphaIndex
                ? 'var(--console-gameslist-alphabet-active-text)'
                : 'var(--console-gameslist-alphabet-text)',
            boxShadow:
              inAlphabet && i === alphaIndex
                ? '0 0 0 2px var(--console-gameslist-alphabet-active-bg)'
                : 'none',
          }"
          @click="jumpToLetter(L)"
        >
          {{ L }}
        </button>
      </div>
    </div>
    <NavigationHint :show-toggle-favorite="true" />
  </div>
</template>

<style scoped>
button:focus {
  outline: none;
}
</style>
