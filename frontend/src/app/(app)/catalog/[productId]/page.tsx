import type { Metadata } from "next";
import { Suspense } from "react";
import { ProductDetail } from "@/components/catalog/product-detail";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Product" };

/** The product id is runtime data (cacheComponents): read it inside a Suspense boundary. */
export default function ProductPage() {
  return (
    <Suspense fallback={<LoadingBlock label="…" />}>
      <ProductDetail />
    </Suspense>
  );
}
