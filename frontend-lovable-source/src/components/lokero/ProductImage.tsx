import { useState } from "react";
import type { Product } from "@/data/lokero";
import { cn } from "@/lib/utils";
import { ProductThumb } from "./CategoryIcon";

type Size = "sm" | "md" | "lg";

const SIZE_CLASS: Record<Size, string> = {
  sm: "h-12 w-12",
  md: "h-16 w-16",
  lg: "h-32 w-32",
};

export function ProductImage({
  product,
  size = "md",
  className,
  eager = false,
}: {
  product: Product;
  size?: Size;
  className?: string;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const explicitUrl = (product as Product & { imageUrl?: string }).imageUrl;
  const src = explicitUrl || `/api/lokero/product-media/${encodeURIComponent(product.id)}`;

  if (failed) {
    return (
      <ProductThumb
        categoryId={product.category}
        size={size === "lg" ? "lg" : size === "sm" ? "sm" : "md"}
        className={className}
      />
    );
  }

  return (
    <div className={cn(SIZE_CLASS[size], "shrink-0 overflow-hidden rounded-xl bg-white p-1", className)}>
      <img
        src={src}
        alt={product.name}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        width={size === "lg" ? 128 : size === "md" ? 64 : 48}
        height={size === "lg" ? 128 : size === "md" ? 64 : 48}
        className="h-full w-full object-contain"
        onError={() => setFailed(true)}
      />
    </div>
  );
}
