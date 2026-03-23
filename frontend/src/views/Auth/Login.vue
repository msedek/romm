<script setup lang="ts">
import { onMounted, ref } from "vue";

const redirecting = ref(true);

onMounted(() => {
  window.open("/api/login/openid", "_self");
});
</script>

<template>
  <v-card class="translucent py-8 px-5" width="500">
    <v-img src="/assets/isotipo.svg" class="mx-auto mb-8" width="80" />
    <v-row class="text-white justify-center mt-2" no-gutters>
      <v-col cols="10" class="text-center">
        <v-progress-circular
          color="primary"
          :width="2"
          :size="24"
          indeterminate
          class="mb-4"
        />
        <p>Signing in with Google...</p>
      </v-col>
    </v-row>
  </v-card>
</template>
