from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable, Iterator

import polars._reexport as pl
from polars import functions as F
from polars.functions.whenthen import WhenThen, WhenThenThen
from polars.utils.convert import _timedelta_to_pl_duration

if TYPE_CHECKING:
    import sys
    from datetime import timedelta

    from polars import DataFrame
    from polars.type_aliases import (
        ClosedInterval,
        IntoExpr,
        RollingInterpolationMethod,
        SchemaDict,
        StartBy,
    )

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


class GroupBy:
    """Starts a new GroupBy operation."""

    def __init__(
        self,
        df: DataFrame,
        by: IntoExpr | Iterable[IntoExpr],
        *more_by: IntoExpr,
        maintain_order: bool,
    ):
        """
        Utility class for performing a groupby operation over the given dataframe.

        Generated by calling ``df.groupby(...)``.

        Parameters
        ----------
        df
            DataFrame to perform the groupby operation over.
        by
            Column or columns to group by. Accepts expression input. Strings are parsed
            as column names.
        *more_by
            Additional columns to group by, specified as positional arguments.
        maintain_order
            Ensure that the order of the groups is consistent with the input data.
            This is slower than a default groupby.

        """
        self.df = df
        self.by = by
        self.more_by = more_by
        self.maintain_order = maintain_order

    def __iter__(self) -> Self:
        """
        Allows iteration over the groups of the groupby operation.

        Returns
        -------
        Iterator returning tuples of (name, data) for each group.

        Examples
        --------
        >>> df = pl.DataFrame({"foo": ["a", "a", "b"], "bar": [1, 2, 3]})
        >>> for name, data in df.groupby("foo"):  # doctest: +SKIP
        ...     print(name)
        ...     print(data)
        ...
        a
        shape: (2, 2)
        ┌─────┬─────┐
        │ foo ┆ bar │
        │ --- ┆ --- │
        │ str ┆ i64 │
        ╞═════╪═════╡
        │ a   ┆ 1   │
        │ a   ┆ 2   │
        └─────┴─────┘
        b
        shape: (1, 2)
        ┌─────┬─────┐
        │ foo ┆ bar │
        │ --- ┆ --- │
        │ str ┆ i64 │
        ╞═════╪═════╡
        │ b   ┆ 3   │
        └─────┴─────┘

        """
        temp_col = "__POLARS_GB_GROUP_INDICES"
        groups_df = (
            self.df.lazy()
            .with_row_count(name=temp_col)
            .groupby(self.by, *self.more_by, maintain_order=self.maintain_order)
            .agg(F.col(temp_col))
            .collect(no_optimization=True)
        )

        group_names = groups_df.select(F.all().exclude(temp_col))

        # When grouping by a single column, group name is a single value
        # When grouping by multiple columns, group name is a tuple of values
        self._group_names: Iterator[object] | Iterator[tuple[object, ...]]
        if (
            isinstance(self.by, (str, pl.Expr, WhenThen, WhenThenThen))
            and not self.more_by
        ):
            self._group_names = iter(group_names.to_series())
        else:
            self._group_names = group_names.iter_rows()

        self._group_indices = groups_df.select(temp_col).to_series()
        self._current_index = 0

        return self

    def __next__(
        self,
    ) -> tuple[object, DataFrame] | tuple[tuple[object, ...], DataFrame]:
        if self._current_index >= len(self._group_indices):
            raise StopIteration

        group_name = next(self._group_names)
        group_data = self.df[self._group_indices[self._current_index]]
        self._current_index += 1

        return group_name, group_data

    def agg(
        self,
        aggs: IntoExpr | Iterable[IntoExpr] | None = None,
        *more_aggs: IntoExpr,
        **named_aggs: IntoExpr,
    ) -> DataFrame:
        """
        Compute aggregations for each group of a groupby operation.

        Parameters
        ----------
        aggs
            Aggregations to compute for each group of the groupby operation.
            Accepts expression input. Strings are parsed as column names.
        *more_aggs
            Additional aggregations, specified as positional arguments.
        **named_aggs
            Additional aggregations, specified as keyword arguments. The resulting
            columns will be renamed to the keyword used.

        Examples
        --------
        Compute the sum of a column for each group.

        >>> df = pl.DataFrame(
        ...     {
        ...         "a": ["a", "b", "a", "b", "c"],
        ...         "b": [1, 2, 1, 3, 3],
        ...         "c": [5, 4, 3, 2, 1],
        ...     }
        ... )
        >>> df.groupby("a").agg(pl.col("b").sum())  # doctest: +IGNORE_RESULT
        shape: (3, 2)
        ┌─────┬─────┐
        │ a   ┆ b   │
        │ --- ┆ --- │
        │ str ┆ i64 │
        ╞═════╪═════╡
        │ a   ┆ 2   │
        │ b   ┆ 5   │
        │ c   ┆ 3   │
        └─────┴─────┘

        Compute multiple aggregates at once by passing a list of expressions.

        >>> df.groupby("a").agg([pl.sum("b"), pl.mean("c")])  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬─────┬─────┐
        │ a   ┆ b   ┆ c   │
        │ --- ┆ --- ┆ --- │
        │ str ┆ i64 ┆ f64 │
        ╞═════╪═════╪═════╡
        │ c   ┆ 3   ┆ 1.0 │
        │ a   ┆ 2   ┆ 4.0 │
        │ b   ┆ 5   ┆ 3.0 │
        └─────┴─────┴─────┘

        Or use positional arguments to compute multiple aggregations in the same way.

        >>> df.groupby("a").agg(
        ...     pl.sum("b").suffix("_sum"),
        ...     (pl.col("c") ** 2).mean().suffix("_mean_squared"),
        ... )  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬───────┬────────────────┐
        │ a   ┆ b_sum ┆ c_mean_squared │
        │ --- ┆ ---   ┆ ---            │
        │ str ┆ i64   ┆ f64            │
        ╞═════╪═══════╪════════════════╡
        │ a   ┆ 2     ┆ 17.0           │
        │ c   ┆ 3     ┆ 1.0            │
        │ b   ┆ 5     ┆ 10.0           │
        └─────┴───────┴────────────────┘

        Use keyword arguments to easily name your expression inputs.

        >>> df.groupby("a").agg(
        ...     b_sum=pl.sum("b"),
        ...     c_mean_squared=(pl.col("c") ** 2).mean(),
        ... )  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬───────┬────────────────┐
        │ a   ┆ b_sum ┆ c_mean_squared │
        │ --- ┆ ---   ┆ ---            │
        │ str ┆ i64   ┆ f64            │
        ╞═════╪═══════╪════════════════╡
        │ a   ┆ 2     ┆ 17.0           │
        │ c   ┆ 3     ┆ 1.0            │
        │ b   ┆ 5     ┆ 10.0           │
        └─────┴───────┴────────────────┘

        """
        return (
            self.df.lazy()
            .groupby(self.by, *self.more_by, maintain_order=self.maintain_order)
            .agg(aggs, *more_aggs, **named_aggs)
            .collect(no_optimization=True)
        )

    def apply(self, function: Callable[[DataFrame], DataFrame]) -> DataFrame:
        """
        Apply a custom/user-defined function (UDF) over the groups as a sub-DataFrame.

        Implementing logic using a Python function is almost always _significantly_
        slower and more memory intensive than implementing the same logic using
        the native expression API because:

        - The native expression engine runs in Rust; UDFs run in Python.
        - Use of Python UDFs forces the DataFrame to be materialized in memory.
        - Polars-native expressions can be parallelised (UDFs cannot).
        - Polars-native expressions can be logically optimised (UDFs cannot).

        Wherever possible you should strongly prefer the native expression API
        to achieve the best performance.

        Parameters
        ----------
        function
            Custom function.

        Returns
        -------
        DataFrame

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "id": [0, 1, 2, 3, 4],
        ...         "color": ["red", "green", "green", "red", "red"],
        ...         "shape": ["square", "triangle", "square", "triangle", "square"],
        ...     }
        ... )
        >>> df
        shape: (5, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 0   ┆ red   ┆ square   │
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        │ 4   ┆ red   ┆ square   │
        └─────┴───────┴──────────┘

        For each color group sample two rows:

        >>> df.groupby("color").apply(
        ...     lambda group_df: group_df.sample(2)
        ... )  # doctest: +IGNORE_RESULT
        shape: (4, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 4   ┆ red   ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        └─────┴───────┴──────────┘

        It is better to implement this with an expression:

        >>> df.filter(
        ...     pl.arange(0, pl.count()).shuffle().over("color") < 2
        ... )  # doctest: +IGNORE_RESULT

        """
        by: list[str]

        if isinstance(self.by, str):
            by = [self.by]
        elif isinstance(self.by, Iterable) and all(isinstance(c, str) for c in self.by):  # type: ignore[union-attr]
            by = list(self.by)  # type: ignore[arg-type]
        else:
            raise TypeError("Cannot call `apply` when grouping by an expression.")

        if all(isinstance(c, str) for c in self.more_by):
            by.extend(self.more_by)  # type: ignore[arg-type]
        else:
            raise TypeError("Cannot call `apply` when grouping by an expression.")

        return self.df.__class__._from_pydf(
            self.df._df.groupby_apply(by, function, self.maintain_order)
        )

    def head(self, n: int = 5) -> DataFrame:
        """
        Get the first `n` rows of each group.

        Parameters
        ----------
        n
            Number of rows to return.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "letters": ["c", "c", "a", "c", "a", "b"],
        ...         "nrs": [1, 2, 3, 4, 5, 6],
        ...     }
        ... )
        >>> df
        shape: (6, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        │ a       ┆ 3   │
        │ c       ┆ 4   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        └─────────┴─────┘
        >>> df.groupby("letters").head(2).sort("letters")
        shape: (5, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ a       ┆ 3   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        └─────────┴─────┘

        """
        return (
            self.df.lazy()
            .groupby(self.by, *self.more_by, maintain_order=self.maintain_order)
            .head(n)
            .collect(no_optimization=True)
        )

    def tail(self, n: int = 5) -> DataFrame:
        """
        Get the last `n` rows of each group.

        Parameters
        ----------
        n
            Number of rows to return.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "letters": ["c", "c", "a", "c", "a", "b"],
        ...         "nrs": [1, 2, 3, 4, 5, 6],
        ...     }
        ... )
        >>> df
        shape: (6, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        │ a       ┆ 3   │
        │ c       ┆ 4   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        └─────────┴─────┘
        >>> df.groupby("letters").tail(2).sort("letters")
        shape: (5, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ a       ┆ 3   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        │ c       ┆ 2   │
        │ c       ┆ 4   │
        └─────────┴─────┘

        """
        return (
            self.df.lazy()
            .groupby(self.by, *self.more_by, maintain_order=self.maintain_order)
            .tail(n)
            .collect(no_optimization=True)
        )

    def all(self) -> DataFrame:
        """
        Aggregate the groups into Series.

        Examples
        --------
        >>> df = pl.DataFrame({"a": ["one", "two", "one", "two"], "b": [1, 2, 3, 4]})
        >>> df.groupby("a", maintain_order=True).all()
        shape: (2, 2)
        ┌─────┬───────────┐
        │ a   ┆ b         │
        │ --- ┆ ---       │
        │ str ┆ list[i64] │
        ╞═════╪═══════════╡
        │ one ┆ [1, 3]    │
        │ two ┆ [2, 4]    │
        └─────┴───────────┘

        """
        return self.agg(F.all())

    def count(self) -> DataFrame:
        """
        Count the number of values in each group.

        .. warning::
            `null` is deemed a value in this context.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).count()
        shape: (3, 2)
        ┌────────┬───────┐
        │ d      ┆ count │
        │ ---    ┆ ---   │
        │ str    ┆ u32   │
        ╞════════╪═══════╡
        │ Apple  ┆ 3     │
        │ Orange ┆ 1     │
        │ Banana ┆ 2     │
        └────────┴───────┘

        """
        return self.agg(F.count())

    def first(self) -> DataFrame:
        """
        Aggregate the first values in the group.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).first()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 1   ┆ 0.5  ┆ true  │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 4   ┆ 13.0 ┆ false │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().first())

    def last(self) -> DataFrame:
        """
        Aggregate the last values in the group.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).last()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 3   ┆ 10.0 ┆ false │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 5   ┆ 14.0 ┆ true  │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().last())

    def max(self) -> DataFrame:
        """
        Reduce the groups to the maximal value.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).max()
        shape: (3, 4)
        ┌────────┬─────┬──────┬──────┐
        │ d      ┆ a   ┆ b    ┆ c    │
        │ ---    ┆ --- ┆ ---  ┆ ---  │
        │ str    ┆ i64 ┆ f64  ┆ bool │
        ╞════════╪═════╪══════╪══════╡
        │ Apple  ┆ 3   ┆ 10.0 ┆ true │
        │ Orange ┆ 2   ┆ 0.5  ┆ true │
        │ Banana ┆ 5   ┆ 14.0 ┆ true │
        └────────┴─────┴──────┴──────┘

        """
        return self.agg(F.all().max())

    def mean(self) -> DataFrame:
        """
        Reduce the groups to the mean values.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).mean()
        shape: (3, 4)
        ┌────────┬─────┬──────────┬──────────┐
        │ d      ┆ a   ┆ b        ┆ c        │
        │ ---    ┆ --- ┆ ---      ┆ ---      │
        │ str    ┆ f64 ┆ f64      ┆ f64      │
        ╞════════╪═════╪══════════╪══════════╡
        │ Apple  ┆ 2.0 ┆ 4.833333 ┆ 0.666667 │
        │ Orange ┆ 2.0 ┆ 0.5      ┆ 1.0      │
        │ Banana ┆ 4.5 ┆ 13.5     ┆ 0.5      │
        └────────┴─────┴──────────┴──────────┘

        """
        return self.agg(F.all().mean())

    def median(self) -> DataFrame:
        """
        Return the median per group.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "d": ["Apple", "Banana", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).median()
        shape: (2, 3)
        ┌────────┬─────┬──────┐
        │ d      ┆ a   ┆ b    │
        │ ---    ┆ --- ┆ ---  │
        │ str    ┆ f64 ┆ f64  │
        ╞════════╪═════╪══════╡
        │ Apple  ┆ 2.0 ┆ 4.0  │
        │ Banana ┆ 4.0 ┆ 13.0 │
        └────────┴─────┴──────┘

        """
        return self.agg(F.all().median())

    def min(self) -> DataFrame:
        """
        Reduce the groups to the minimal value.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).min()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 1   ┆ 0.5  ┆ false │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 4   ┆ 13.0 ┆ false │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().min())

    def n_unique(self) -> DataFrame:
        """
        Count the unique values per group.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 1, 3, 4, 5],
        ...         "b": [0.5, 0.5, 0.5, 10, 13, 14],
        ...         "d": ["Apple", "Banana", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).n_unique()
        shape: (2, 3)
        ┌────────┬─────┬─────┐
        │ d      ┆ a   ┆ b   │
        │ ---    ┆ --- ┆ --- │
        │ str    ┆ u32 ┆ u32 │
        ╞════════╪═════╪═════╡
        │ Apple  ┆ 2   ┆ 2   │
        │ Banana ┆ 3   ┆ 3   │
        └────────┴─────┴─────┘

        """
        return self.agg(F.all().n_unique())

    def quantile(
        self, quantile: float, interpolation: RollingInterpolationMethod = "nearest"
    ) -> DataFrame:
        """
        Compute the quantile per group.

        Parameters
        ----------
        quantile
            Quantile between 0.0 and 1.0.
        interpolation : {'nearest', 'higher', 'lower', 'midpoint', 'linear'}
            Interpolation method.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).quantile(1)
        shape: (3, 3)
        ┌────────┬─────┬──────┐
        │ d      ┆ a   ┆ b    │
        │ ---    ┆ --- ┆ ---  │
        │ str    ┆ f64 ┆ f64  │
        ╞════════╪═════╪══════╡
        │ Apple  ┆ 3.0 ┆ 10.0 │
        │ Orange ┆ 2.0 ┆ 0.5  │
        │ Banana ┆ 5.0 ┆ 14.0 │
        └────────┴─────┴──────┘

        """
        return self.agg(F.all().quantile(quantile, interpolation=interpolation))

    def sum(self) -> DataFrame:
        """
        Reduce the groups to the sum.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... )
        >>> df.groupby("d", maintain_order=True).sum()
        shape: (3, 4)
        ┌────────┬─────┬──────┬─────┐
        │ d      ┆ a   ┆ b    ┆ c   │
        │ ---    ┆ --- ┆ ---  ┆ --- │
        │ str    ┆ i64 ┆ f64  ┆ u32 │
        ╞════════╪═════╪══════╪═════╡
        │ Apple  ┆ 6   ┆ 14.5 ┆ 2   │
        │ Orange ┆ 2   ┆ 0.5  ┆ 1   │
        │ Banana ┆ 9   ┆ 27.0 ┆ 1   │
        └────────┴─────┴──────┴─────┘

        """
        return self.agg(F.all().sum())


class RollingGroupBy:
    """
    A rolling grouper.

    This has an `.agg` method which will allow you to run all polars expressions in a
    groupby context.
    """

    def __init__(
        self,
        df: DataFrame,
        index_column: IntoExpr,
        period: str | timedelta,
        offset: str | timedelta | None,
        closed: ClosedInterval,
        by: IntoExpr | Iterable[IntoExpr] | None,
        check_sorted: bool,
    ):
        period = _timedelta_to_pl_duration(period)
        offset = _timedelta_to_pl_duration(offset)

        self.df = df
        self.time_column = index_column
        self.period = period
        self.offset = offset
        self.closed = closed
        self.by = by
        self.check_sorted = check_sorted

    def __iter__(self) -> Self:
        temp_col = "__POLARS_GB_GROUP_INDICES"
        groups_df = (
            self.df.lazy()
            .with_row_count(name=temp_col)
            .groupby_rolling(
                index_column=self.time_column,
                period=self.period,
                offset=self.offset,
                closed=self.closed,
                by=self.by,
                check_sorted=self.check_sorted,
            )
            .agg(F.col(temp_col))
            .collect(no_optimization=True)
        )

        group_names = groups_df.select(F.all().exclude(temp_col))

        # When grouping by a single column, group name is a single value
        # When grouping by multiple columns, group name is a tuple of values
        self._group_names: Iterator[object] | Iterator[tuple[object, ...]]
        if self.by is None:
            self._group_names = iter(group_names.to_series())
        else:
            self._group_names = group_names.iter_rows()

        self._group_indices = groups_df.select(temp_col).to_series()
        self._current_index = 0

        return self

    def __next__(
        self,
    ) -> tuple[object, DataFrame] | tuple[tuple[object, ...], DataFrame]:
        if self._current_index >= len(self._group_indices):
            raise StopIteration

        group_name = next(self._group_names)
        group_data = self.df[self._group_indices[self._current_index]]
        self._current_index += 1

        return group_name, group_data

    def agg(
        self,
        aggs: IntoExpr | Iterable[IntoExpr] | None = None,
        *more_aggs: IntoExpr,
        **named_aggs: IntoExpr,
    ) -> DataFrame:
        return (
            self.df.lazy()
            .groupby_rolling(
                index_column=self.time_column,
                period=self.period,
                offset=self.offset,
                closed=self.closed,
                by=self.by,
                check_sorted=self.check_sorted,
            )
            .agg(aggs, *more_aggs, **named_aggs)
            .collect(no_optimization=True)
        )

    def apply(
        self,
        function: Callable[[DataFrame], DataFrame],
        schema: SchemaDict | None,
    ) -> DataFrame:
        """
        Apply a custom/user-defined function (UDF) over the groups as a new DataFrame.

        Using this is considered an anti-pattern. This will be very slow because:

        - it forces the engine to materialize the whole `DataFrames` for the groups.
        - it is not parallelized
        - it blocks optimizations as the passed python function is opaque to the
          optimizer

        The idiomatic way to apply custom functions over multiple columns is using:

        `pl.struct([my_columns]).apply(lambda struct_series: ..)`

        Parameters
        ----------
        function
            Function to apply over each group of the `LazyFrame`.
        schema
            Schema of the output function. This has to be known statically. If the
            given schema is incorrect, this is a bug in the caller's query and may
            lead to errors. If set to None, polars assumes the schema is unchanged.


        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "id": [0, 1, 2, 3, 4],
        ...         "color": ["red", "green", "green", "red", "red"],
        ...         "shape": ["square", "triangle", "square", "triangle", "square"],
        ...     }
        ... )
        >>> df
        shape: (5, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 0   ┆ red   ┆ square   │
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        │ 4   ┆ red   ┆ square   │
        └─────┴───────┴──────────┘

        For each color group sample two rows:

        >>> (
        ...     df.lazy()
        ...     .groupby("color")
        ...     .apply(lambda group_df: group_df.sample(2), schema=None)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT
        shape: (4, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 4   ┆ red   ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        └─────┴───────┴──────────┘

        It is better to implement this with an expression:

        >>> (
        ...     df.lazy()
        ...     .filter(pl.arange(0, pl.count()).shuffle().over("color") < 2)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT

        """
        return (
            self.df.lazy()
            .groupby_rolling(
                index_column=self.time_column,
                period=self.period,
                offset=self.offset,
                closed=self.closed,
                by=self.by,
                check_sorted=self.check_sorted,
            )
            .apply(function, schema)
            .collect(no_optimization=True)
        )


class DynamicGroupBy:
    """
    A dynamic grouper.

    This has an `.agg` method which allows you to run all polars expressions in a
    groupby context.
    """

    def __init__(
        self,
        df: DataFrame,
        index_column: IntoExpr,
        every: str | timedelta,
        period: str | timedelta | None,
        offset: str | timedelta | None,
        truncate: bool,
        include_boundaries: bool,
        closed: ClosedInterval,
        by: IntoExpr | Iterable[IntoExpr] | None,
        start_by: StartBy,
        check_sorted: bool,
    ):
        every = _timedelta_to_pl_duration(every)
        period = _timedelta_to_pl_duration(period)
        offset = _timedelta_to_pl_duration(offset)

        self.df = df
        self.time_column = index_column
        self.every = every
        self.period = period
        self.offset = offset
        self.truncate = truncate
        self.include_boundaries = include_boundaries
        self.closed = closed
        self.by = by
        self.start_by = start_by
        self.check_sorted = check_sorted

    def __iter__(self) -> Self:
        temp_col = "__POLARS_GB_GROUP_INDICES"
        groups_df = (
            self.df.lazy()
            .with_row_count(name=temp_col)
            .groupby_dynamic(
                index_column=self.time_column,
                every=self.every,
                period=self.period,
                offset=self.offset,
                truncate=self.truncate,
                include_boundaries=self.include_boundaries,
                closed=self.closed,
                by=self.by,
                start_by=self.start_by,
                check_sorted=self.check_sorted,
            )
            .agg(F.col(temp_col))
            .collect(no_optimization=True)
        )

        group_names = groups_df.select(F.all().exclude(temp_col))

        # When grouping by a single column, group name is a single value
        # When grouping by multiple columns, group name is a tuple of values
        self._group_names: Iterator[object] | Iterator[tuple[object, ...]]
        if self.by is None:
            self._group_names = iter(group_names.to_series())
        else:
            self._group_names = group_names.iter_rows()

        self._group_indices = groups_df.select(temp_col).to_series()
        self._current_index = 0

        return self

    def __next__(
        self,
    ) -> tuple[object, DataFrame] | tuple[tuple[object, ...], DataFrame]:
        if self._current_index >= len(self._group_indices):
            raise StopIteration

        group_name = next(self._group_names)
        group_data = self.df[self._group_indices[self._current_index]]
        self._current_index += 1

        return group_name, group_data

    def agg(
        self,
        aggs: IntoExpr | Iterable[IntoExpr] | None = None,
        *more_aggs: IntoExpr,
        **named_aggs: IntoExpr,
    ) -> DataFrame:
        return (
            self.df.lazy()
            .groupby_dynamic(
                index_column=self.time_column,
                every=self.every,
                period=self.period,
                offset=self.offset,
                truncate=self.truncate,
                include_boundaries=self.include_boundaries,
                closed=self.closed,
                by=self.by,
                start_by=self.start_by,
                check_sorted=self.check_sorted,
            )
            .agg(aggs, *more_aggs, **named_aggs)
            .collect(no_optimization=True)
        )

    def apply(
        self,
        function: Callable[[DataFrame], DataFrame],
        schema: SchemaDict | None,
    ) -> DataFrame:
        """
        Apply a custom/user-defined function (UDF) over the groups as a new DataFrame.

        Using this is considered an anti-pattern. This will be very slow because:

        - it forces the engine to materialize the whole `DataFrames` for the groups.
        - it is not parallelized
        - it blocks optimizations as the passed python function is opaque to the
          optimizer

        The idiomatic way to apply custom functions over multiple columns is using:

        `pl.struct([my_columns]).apply(lambda struct_series: ..)`

        Parameters
        ----------
        function
            Function to apply over each group of the `LazyFrame`.
        schema
            Schema of the output function. This has to be known statically. If the
            given schema is incorrect, this is a bug in the caller's query and may
            lead to errors. If set to None, polars assumes the schema is unchanged.


        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "id": [0, 1, 2, 3, 4],
        ...         "color": ["red", "green", "green", "red", "red"],
        ...         "shape": ["square", "triangle", "square", "triangle", "square"],
        ...     }
        ... )
        >>> df
        shape: (5, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 0   ┆ red   ┆ square   │
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        │ 4   ┆ red   ┆ square   │
        └─────┴───────┴──────────┘

        For each color group sample two rows:

        >>> (
        ...     df.lazy()
        ...     .groupby("color")
        ...     .apply(lambda group_df: group_df.sample(2), schema=None)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT
        shape: (4, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 4   ┆ red   ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        └─────┴───────┴──────────┘

        It is better to implement this with an expression:

        >>> (
        ...     df.lazy()
        ...     .filter(pl.arange(0, pl.count()).shuffle().over("color") < 2)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT

        """
        return (
            self.df.lazy()
            .groupby_dynamic(
                index_column=self.time_column,
                every=self.every,
                period=self.period,
                offset=self.offset,
                truncate=self.truncate,
                include_boundaries=self.include_boundaries,
                closed=self.closed,
                by=self.by,
                start_by=self.start_by,
                check_sorted=self.check_sorted,
            )
            .apply(function, schema)
            .collect(no_optimization=True)
        )
