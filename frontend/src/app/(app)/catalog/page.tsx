import type { Metadata } from "next";
import { ProductsView } from "@/components/catalog/products-view";

export const metadata: Metadata = { title: "Products" };

export default function CatalogPage() {
  return <ProductsView />;
}
