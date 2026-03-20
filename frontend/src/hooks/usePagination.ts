import { useState, useCallback } from "react";

export function usePagination(initialPageSize = 25) {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(initialPageSize);

  const reset = useCallback(() => setPage(1), []);

  return { page, pageSize, setPage, reset };
}
